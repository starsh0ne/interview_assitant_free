"""DeepSeek 实现（OpenAI 兼容接口，模型 deepseek-flash / V4.1-Flash）。

思考强度三档（实测 2026-11-25，api.deepseek.com）：
- flash 是混合思考模型：默认/effort 均先输出 reasoning_content（1.5~3s 思考链）
- 官方关闭思考的参数为 thinking={"type": "disabled"}（reasoning:false 等形式均无效）
- disabled 实测首 token 363~761ms；enabled+effort=high 首约 1.9s

映射：
- LOW    低  → thinking disabled + max_tokens 400，首条 0.4~0.8s 上屏（默认）
- MEDIUM 中  → thinking disabled + max_tokens 700，速度同低、篇幅更完整
- HIGH   高  → thinking enabled + effort high，深度换速度（赛前重题用）
"""
from __future__ import annotations

import time

from openai import OpenAI

from app.core.config import AppConfig
from app.core.models import Answer, ThinkLevel
from app.llm.base import AnswerRequest, BaseLLM
from app.logging_conf import get_logger

MODULE = "llm"

THINK_PARAMS = {
    ThinkLevel.LOW: {"thinking": {"type": "disabled"}, "max_tokens": 400},
    ThinkLevel.MEDIUM: {"thinking": {"type": "disabled"}, "max_tokens": 700},
    ThinkLevel.HIGH: {"thinking": {"type": "enabled"}, "effort": "high", "max_tokens": 1600},
}

SYSTEM_PROMPT = """你是就业面试的实时辅助教练：面试官刚问完一个问题，候选人需要能立刻说出口的回答。

【输出格式】纯文本，每行一条，禁止 JSON、编号、项目符号（不要用 - 或 * 开头）：
第 1 行：一句话直接回答（15~40 字口语，立刻可照着说）
第 2 行起：可展开的要点行，每行 15~50 字，必须含具体细节或数字
要点行数由问题复杂度决定：事实性问题（版本/年限/是什么）0~1 行；常规问题 2~3 行；项目/场景/系统设计题 3~5 行

【语言风格】
口语衔接（"重点是/另外/项目里其实"），禁书面腔（首先/其次/综上所述/总而言之/值得注意的是）。
长度原则：该短则短，宁可少而具体，不要多而空洞；禁止每题等长。"""


class DeepSeekLLM(BaseLLM):
    name = "deepseek"

    def __init__(self, config: AppConfig):
        self.config = config
        self.client = OpenAI(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
            timeout=30.0,
            max_retries=1,
        )

    # ---- 流式主路径（answer 也复用，收集完即完整结果） ----

    def answer_stream(self, req: AnswerRequest, on_line) -> Answer:
        level = req.think_level or ThinkLevel.LOW
        params = THINK_PARAMS.get(level, THINK_PARAMS[ThinkLevel.LOW])

        user_prompt = self._build_user_prompt(req)
        stream = self.client.chat.completions.create(
            model=self.config.deepseek_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=params["max_tokens"],
            stream=True,
            extra_body={k: v for k, v in params.items() if k != "max_tokens"},
        )

        lines: list[str] = []
        first_line_ts = None
        start = time.perf_counter()
        buf = ""
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if not (delta and delta.content):
                continue
            buf += delta.content
            while "\n" in buf:
                raw, buf = buf.split("\n", 1)
                line = self._clean_line(raw)
                if line:
                    lines.append(line)
                    if first_line_ts is None:
                        first_line_ts = time.perf_counter()
                        get_logger().info(
                            "流式首行到达", module=MODULE,
                            location="DeepSeekLLM.answer_stream", status="success",
                            first_line_ms=int((first_line_ts - start) * 1000))
                    on_line("opener" if len(lines) == 1 else "point", line)
        tail = self._clean_line(buf)
        if tail:
            lines.append(tail)
            on_line("opener" if len(lines) == 1 else "point", tail)

        opener = lines[0] if lines else ""
        points = lines[1:]
        if not points:
            points = ["（模型只回了一行，可结合速查卡自行展开）"]
        return Answer(question=req.question, opener=opener, points=points,
                      trace_id=req.trace_id, think_level=level.value)

    def answer(self, req: AnswerRequest) -> Answer:
        """非流式入口（测试/mock 场景用）：复用流式实现，收集完返回。"""
        return self.answer_stream(req, lambda kind, text: None)

    def warmup(self) -> None:
        """预热：极小请求建立 TLS 连接，消除首次真实请求的建连开销。"""
        try:
            self.client.chat.completions.create(
                model=self.config.deepseek_model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                stream=False,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except Exception:
            pass  # 预热失败不阻塞（可能未配 Key）

    # ---- 工具 ----

    @staticmethod
    def _clean_line(raw: str) -> str:
        """剥掉模型偶尔带的编号/符号前缀与空白。"""
        return raw.strip().lstrip("-•*·—0123456789.、) ").strip()

    @staticmethod
    def _build_user_prompt(req: AnswerRequest) -> str:
        parts = []
        if req.resume_text.strip():
            parts.append(f"【候选人速查卡】\n{req.resume_text[:6000]}")
        if req.self_context.strip():
            parts.append(f"【候选人此前的回答（供衔接）】\n{req.self_context[:1000]}")
        parts.append(f"【面试官的问题】\n{req.question}")
        return "\n\n".join(parts)
