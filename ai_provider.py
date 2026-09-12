"""
AI provayder qatlami — ai_sales.py modelni faqat shu yerdan chaqiradi.

Nega alohida qatlam: suhbat mantiqi (vositalar, buyurtma, lokatsiya, guruh
qoidalari) provayderga bog'liq emas, lekin OpenAI va Anthropic API lari
tubdan boshqacha gapiradi. Shu fayl ikkalasini bitta ko'rinishga keltiradi:
`step()` bitta model chaqiruvi, `Turn` uning natijasi (matn + vosita
chaqiruvlari). ai_sales.py qaysi provayder ishlayotganini bilmaydi ham.

QAYSI PROVAYDER
  AI_PROVIDER=openai | anthropic. Berilmasa — qaysi kalit bor bo'lsa o'sha
  (ikkalasi ham bo'lsa OpenAI; egasi 2026-09-13 da OpenAI ni tanladi).

OPENAI — Responses API, Chat Completions EMAS
  GPT-5.x da vosita + fikrlash (reasoning_effort) Chat Completions da 400
  qaytaradi: "Function tools with reasoning_effort are not supported ... use
  /v1/responses". Shuning uchun Responses API. Suhbat holati serverda:
  har javobning id si keyingi so'rovga previous_response_id bo'lib ketadi,
  ya'ni fikrlash bloklarini o'zimiz qayta yuborishimiz shart emas.
  `instructions` zanjirda saqlanmaydi — har chaqiruvda qayta beriladi.

ANTHROPIC — Messages API
  Tarix bizda (state["messages"]), tizim prompti ikki bo'lakda keshlanadi.
"""
import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

DEFAULT_MODELS = {"openai": "gpt-5.5", "anthropic": "claude-opus-5"}

# 1M token uchun $ narx: (kirish, keshlangan kirish, chiqish).
# OpenAI — developers.openai.com/api/docs/pricing dan 2026-09-13 da olingan,
# 272K dan qisqa kontekst uchun. Anthropic — o'sha kundagi rasmiy jadval;
# kesh yozish (1.25x) hisobga olinmagan, ya'ni Anthropic summasi biroz past
# chiqadi. Narx o'zgarsa shu jadvalni yangilash kifoya.
PRICES = {
    "gpt-5.5": (5.00, 0.50, 30.00),
    "gpt-5.4": (2.50, 0.25, 15.00),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "claude-opus-5": (5.00, 0.50, 25.00),
    "claude-sonnet-5": (2.00, 0.20, 10.00),
    "claude-haiku-4-5": (1.00, 0.10, 5.00),
}


def price_for(model: str) -> tuple[float, float, float] | None:
    """Sanali variantlar ('gpt-5.5-2026-04-23') ham asosiy nomiga tushadi."""
    if model in PRICES:
        return PRICES[model]
    for base in sorted(PRICES, key=len, reverse=True):
        if model.startswith(base + "-"):
            return PRICES[base]
    return None


def estimate_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """$ hisobida. `input_tokens` — keshlangani bilan birga JAMI kirish.
    Narxi noma'lum model uchun 0 qaytadi (hisobotda 'narx noma'lum' deyiladi)."""
    price = price_for(model)
    if not price:
        return 0.0
    fresh = max(0, input_tokens - cached_tokens)
    return (fresh * price[0] + cached_tokens * price[1] + output_tokens * price[2]) / 1_000_000


# OpenAI zanjiri serverda o'sib boradi va har so'rovda butun zanjir kirish
# tokeni bo'lib hisoblanadi. Savdo suhbati qisqa, lekin cheksiz qolmasin.
OPENAI_CHAIN_LIMIT = 60


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ToolResult:
    id: str
    output: str
    is_error: bool = False


@dataclass
class Usage:
    """Bitta chaqiruv sarfi. input — keshlangani bilan birga jami kirish;
    output — fikrlash tokenlari ham shu yerda (ikkala provayder ham shunday
    hisoblaydi va shunday oladi)."""
    input: int = 0
    cached: int = 0
    output: int = 0


@dataclass
class Turn:
    """Bitta model chaqiruvining natijasi, provayderdan qat'i nazar."""
    text: str = ""
    calls: list = field(default_factory=list)
    refused: bool = False
    usage: Usage = field(default_factory=Usage)


@dataclass
class Tool:
    """Vosita ta'rifi — neytral ko'rinishda, har provayder o'zicha chizadi."""
    name: str
    description: str
    schema: dict
    strict: bool = False


def _chosen_provider() -> str:
    wanted = os.getenv("AI_PROVIDER", "").strip().lower()
    if wanted in ("openai", "anthropic"):
        return wanted
    if OPENAI_KEY:
        return "openai"
    if ANTHROPIC_KEY:
        return "anthropic"
    return ""


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, effort: str):
        self.api_key, self.model, self.effort = api_key, model, effort
        self.client = None

    def _get_client(self):
        if self.client is None:
            from anthropic import AsyncAnthropic
            self.client = AsyncAnthropic(api_key=self.api_key)
        return self.client

    @staticmethod
    def render_tools(tools: list[Tool]) -> list[dict]:
        out = []
        for t in tools:
            spec = {"name": t.name, "description": t.description, "input_schema": t.schema}
            if t.strict:
                spec["strict"] = True
            out.append(spec)
        return out

    @staticmethod
    def render_system(rules: str, catalog: str) -> list[dict]:
        # Ikki bo'lak, ikkalasi keshlanadi: qoidalar hech qachon o'zgarmaydi,
        # katalog 5 daqiqada bir yangilanadi.
        return [
            {"type": "text", "text": rules, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": catalog, "cache_control": {"type": "ephemeral"}},
        ]

    async def step(self, state: dict, rules: str, catalog: str, tools: list[Tool] | None,
                   *, user: str | None = None, results: list[ToolResult] | None = None,
                   max_tokens: int = 800, history_limit: int = 40) -> Turn:
        messages = state.setdefault("messages", [])
        if user is not None:
            messages.append({"role": "user", "content": user})
            _trim_at_user_turn(messages, history_limit)
        if results is not None:
            # Hamma natija BITTA user xabarida — bo'lib yuborilsa model keyingi
            # safar parallel chaqiruvni tashlab ketadi.
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": r.id, "content": r.output,
                 "is_error": r.is_error} for r in results
            ]})

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": self.render_system(rules, catalog),
            "output_config": {"effort": self.effort},
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = self.render_tools(tools)
        response = await self._get_client().messages.create(**kwargs)
        messages.append({"role": "assistant", "content": response.content})
        usage = _anthropic_usage(getattr(response, "usage", None))

        if response.stop_reason == "refusal":
            return Turn(refused=True, usage=usage)
        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        calls = []
        if response.stop_reason == "tool_use":
            calls = [ToolCall(b.id, b.name, dict(b.input))
                     for b in response.content if b.type == "tool_use"]
        return Turn(text=text, calls=calls, usage=usage)


def _anthropic_usage(u) -> Usage:
    """Anthropic input_tokens ga keshdan o'qilgan va keshga yozilgan qism
    KIRMAYDI — jami kirish uchun uchalasini qo'shamiz."""
    if u is None:
        return Usage()
    read = int(getattr(u, "cache_read_input_tokens", 0) or 0)
    write = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    fresh = int(getattr(u, "input_tokens", 0) or 0)
    return Usage(input=fresh + read + write, cached=read,
                 output=int(getattr(u, "output_tokens", 0) or 0))


def _trim_at_user_turn(messages: list, limit: int) -> None:
    """Tarixni kesadi, lekin faqat oddiy user matni boshlanadigan joydan —
    tool_use ni o'z tool_result idan ajratib qo'ysak API 400 qaytaradi."""
    if len(messages) <= limit:
        return
    cut = len(messages) - limit
    while cut < len(messages):
        m = messages[cut]
        if m["role"] == "user" and isinstance(m["content"], str):
            break
        cut += 1
    del messages[:cut]


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str, effort: str):
        self.api_key, self.model, self.effort = api_key, model, effort
        self.client = None

    def _get_client(self):
        if self.client is None:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=self.api_key)
        return self.client

    @staticmethod
    def render_tools(tools: list[Tool]) -> list[dict]:
        out = []
        for t in tools:
            props = set((t.schema.get("properties") or {}).keys())
            required = set(t.schema.get("required") or [])
            # OpenAI strict rejimi HAMMA maydonni required da talab qiladi.
            # Ixtiyoriy maydoni bor vositada strict ni o'chiramiz — aks holda
            # so'rov 400 bilan qaytadi.
            spec = {"type": "function", "name": t.name, "description": t.description,
                    "parameters": t.schema, "strict": bool(t.strict and props == required)}
            out.append(spec)
        return out

    async def step(self, state: dict, rules: str, catalog: str, tools: list[Tool] | None,
                   *, user: str | None = None, results: list[ToolResult] | None = None,
                   max_tokens: int = 800, history_limit: int = 40) -> Turn:
        if user is not None:
            if state.get("turns", 0) >= OPENAI_CHAIN_LIMIT:
                state.pop("prev_id", None)   # juda uzun zanjir — yangidan boshlaymiz
                state["turns"] = 0
            items = [{"role": "user", "content": user}]
        else:
            items = [{"type": "function_call_output", "call_id": r.id, "output": r.output}
                     for r in (results or [])]

        kwargs = {
            "model": self.model,
            "instructions": rules + "\n\n" + catalog,
            "input": items,
            "reasoning": {"effort": self.effort},
            "max_output_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = self.render_tools(tools)
        if state.get("prev_id"):
            kwargs["previous_response_id"] = state["prev_id"]

        response = await self._get_client().responses.create(**kwargs)
        state["prev_id"] = response.id
        state["turns"] = state.get("turns", 0) + 1

        usage = _openai_usage(getattr(response, "usage", None))
        refused = False
        calls = []
        for item in response.output or []:
            if item.type == "function_call":
                try:
                    args = json.loads(item.arguments or "{}")
                except ValueError:
                    args = {}
                calls.append(ToolCall(item.call_id, item.name, args))
            elif item.type == "message":
                refused = refused or any(
                    getattr(part, "type", "") == "refusal" for part in (item.content or []))
        if refused and not calls:
            return Turn(refused=True, usage=usage)
        return Turn(text=(response.output_text or "").strip(), calls=calls, usage=usage)


def _openai_usage(u) -> Usage:
    """OpenAI input_tokens keshlanganini ham o'z ichiga oladi; fikrlash
    tokenlari output_tokens ichida."""
    if u is None:
        return Usage()
    details = getattr(u, "input_tokens_details", None)
    return Usage(input=int(getattr(u, "input_tokens", 0) or 0),
                 cached=int(getattr(details, "cached_tokens", 0) or 0),
                 output=int(getattr(u, "output_tokens", 0) or 0))


def reset(state: dict) -> None:
    """Xato bo'lgan suhbatni tozalaydi. OpenAI da muhim: javobsiz qolgan
    function_call bor zanjirga keyingi xabar yuborilsa API 400 qaytaradi."""
    state.pop("prev_id", None)
    state.pop("turns", None)
    state.pop("messages", None)


def build(model: str = "", effort: str = "low"):
    """Sozlamalarga qarab provayder obyektini qaytaradi, kalit bo'lmasa None."""
    provider = _chosen_provider()
    if provider == "openai" and OPENAI_KEY:
        return OpenAIProvider(OPENAI_KEY, model or DEFAULT_MODELS["openai"], effort)
    if provider == "anthropic" and ANTHROPIC_KEY:
        return AnthropicProvider(ANTHROPIC_KEY, model or DEFAULT_MODELS["anthropic"], effort)
    if provider:
        logger.warning("AI_PROVIDER=%s, lekin uning kaliti yo'q — AI o'chiq", provider)
    return None
