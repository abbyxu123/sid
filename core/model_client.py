"""模型客户端：llama-server (OpenAI 兼容) 封装 + 大小模型分工。

- Step 3.7（:8080，深思）：多模态、复杂结构化、议事会仲裁、Auditor
- kitten（:8081，直觉，可选）：结构化抽取、专业 Actor 快评分
环境变量：STEP_BASE_URL / KITTEN_BASE_URL / USE_KITTEN=1
任何调用失败都抛 ModelError，由编排层降级到规则路径——模型不可用绝不阻塞主闭环。
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx

from skills.food.agents.extraction import SYSTEM_PROMPT as EXTRACT_PROMPT
from skills.food.agents.extraction import parse_json_loose, unflatten
from skills.food.agents.prompts import AGENT_OUTPUT_SCHEMA, build_agent_messages

from .decision_schema import AgentScore, Candidate, DecisionSession


class ModelError(RuntimeError):
    pass


class ChatEndpoint:
    def __init__(self, base_url: str, model: str, max_tokens: int, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def chat(self, messages: list[dict], *, temperature: float = 0.6,
                   response_schema: dict | None = None, max_tokens: int | None = None) -> str:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature,
            "top_p": 0.95,
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": response_schema},
            }
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(f"{self.base_url}/v1/chat/completions",
                                      json=payload, timeout=self.timeout)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"].get("content") or ""
                if not content.strip():
                    raise ModelError("empty content (reasoning ate max_tokens?)")
                return content
        except httpx.HTTPError as e:
            raise ModelError(f"{type(e).__name__}: {e}") from e
        except (KeyError, IndexError, TypeError, ValueError) as e:
            # 200 但响应体畸形也必须走 ModelError 契约，降级路径才接得住
            raise ModelError(f"malformed response: {type(e).__name__}: {e}") from e

    async def healthy(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{self.base_url}/health", timeout=3)
                return r.status_code == 200
        except httpx.HTTPError:
            return False


class ModelRouter:
    """深思-直觉分工：抽取/Actor 优先 kitten（若启用且在线），仲裁/审核永远 Step。"""

    def __init__(self):
        self.step = ChatEndpoint(
            os.environ.get("STEP_BASE_URL", "http://127.0.0.1:8080"),
            os.environ.get("STEP_MODEL", "step-local"), max_tokens=1600)
        self.kitten: ChatEndpoint | None = None
        if os.environ.get("USE_KITTEN") == "1":
            self.kitten = ChatEndpoint(
                os.environ.get("KITTEN_BASE_URL", "http://127.0.0.1:8081"),
                os.environ.get("KITTEN_MODEL", "kitten-nlu"), max_tokens=600)
        self.agent_concurrency = int(os.environ.get("AGENT_CONCURRENCY", "3"))

    async def _fast_or_step(self) -> ChatEndpoint:
        if self.kitten and await self.kitten.healthy():
            return self.kitten
        return self.step

    async def structure_input(self, text: str):
        """用户原话 → (goal, HardConstraints, SoftPreferences, Context)。"""
        ep = await self._fast_or_step()
        for attempt in range(2):
            try:
                # Step 是 reasoning 模型：默认 1600 会被思考链吃光返回空（同菜单/卡路里的病）
                content = await ep.chat(
                    [{"role": "system", "content": EXTRACT_PROMPT},
                     {"role": "user", "content": text}],
                    temperature=0.2,
                    max_tokens=2800 if ep is self.step else None)
                return unflatten(parse_json_loose(content))
            except (ModelError, ValueError, json.JSONDecodeError) as e:
                if attempt == 0 and ep is not self.step:
                    ep = self.step  # kitten 失败升级 Step 重试
                    continue
                raise ModelError(f"structure_input failed: {e}") from e

    async def agent_score(self, agent: str, session: DecisionSession,
                          candidates: list[Candidate],
                          ledger_recent: list | None = None) -> list[AgentScore]:
        # Actor 默认走 Step 本尊；只有 scorer kitten（kitten ②）训好并显式开启后才下放
        use_kitten_actors = os.environ.get("KITTEN_ACTORS") == "1"
        ep = await self._fast_or_step() if use_kitten_actors else self.step
        messages = build_agent_messages(agent, session, candidates, ledger_recent)
        # Step 是 reasoning 模型：思考链 ~700 tok + 每候选 ~100 tok，预算不足会截断 JSON
        budget = (1100 + 150 * len(candidates)) if ep is self.step else (150 + 80 * len(candidates))
        content = await ep.chat(messages, temperature=1.0,
                                response_schema=AGENT_OUTPUT_SCHEMA,
                                max_tokens=budget)
        rows = json.loads(content)
        return [AgentScore(**r) for r in rows]

    async def parse_menu_image(self, image_b64: str, mime: str = "image/png") -> dict:
        """菜单照片 → {restaurant, items: [{name, price}], delivery_fee}。只有 Step 能做（多模态）。"""
        prompt = ('这是一张餐厅菜单照片。提取全部菜品与价格，只输出 JSON：'
                  '{"restaurant": "店名", "items": [{"name": "菜名", "price": 数字}], '
                  '"delivery_fee": 数字或null}')
        content = await self.step.chat(
            [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ]}],
            # Step reasoning 思考链 ~1500 tok + 每菜品 ~40 tok；1600 会被思考吃光返回空
            temperature=0.6, max_tokens=3600)
        return parse_json_loose(content)

    async def council(self, agents: list[str], session: DecisionSession,
                      candidates: list[Candidate],
                      ledger_recent: list | None = None,
                      sink: dict | None = None,
                      on_agent=None) -> dict[str, list[AgentScore]]:
        """并发议事会：并发槽位限制 + 单 Agent 失败不拖垮全会（缺席交给评分器中性处理）。
        sink: 传入 session.agent_scores 可让 SSE 实时看到每只猫陆续完成。"""
        sem = asyncio.Semaphore(self.agent_concurrency)
        scores: dict[str, list[AgentScore]] = sink if sink is not None else {}

        async def run(agent: str):
            async with sem:
                try:
                    scores[agent] = await self.agent_score(agent, session, candidates, ledger_recent)
                    if on_agent:
                        await on_agent(agent)
                except (ModelError, json.JSONDecodeError, ValueError, TypeError):
                    pass

        await asyncio.gather(*[run(a) for a in agents])
        if not scores:
            raise ModelError("all agents failed")
        return scores
