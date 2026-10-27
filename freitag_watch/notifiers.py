from __future__ import annotations

import html
import os
import smtplib
from collections import defaultdict
from email.message import EmailMessage
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence
from urllib.parse import quote

import requests

from .config import USER_AGENT, website_url


def _event_product(state: Mapping[str, Any], event: Mapping[str, Any]) -> Mapping[str, Any]:
    return state.get("products", {}).get(event.get("product_id"), {})


def prepare_notifications(state: MutableMapping[str, Any], now: str) -> int:
    """Move eligible deliveries to 'sending' before the state is persisted.

    The workflow persists this state before contacting Bark/SMTP. If a process
    dies after external delivery, the next run reports an unknown delivery
    instead of blindly duplicating it.
    """
    bark_configured = bool(os.getenv("BARK_KEY"))
    email_configured = os.getenv("EMAIL_ENABLED", "false").lower() == "true" and bool(os.getenv("SMTP_PASSWORD"))
    count = 0
    for event in state.get("events", []):
        product = _event_product(state, event)
        bark = event.setdefault("bark", {"status": "pending", "attempts": 0})
        if bark_configured and bark.get("status") in ("pending", "failed") and int(bark.get("attempts", 0)) < 3:
            bark.update({"status": "sending", "prepared_at": now, "attempts": int(bark.get("attempts", 0)) + 1})
            count += 1
        pattern = product.get("pattern") or {}
        email_state = event.setdefault("email", {"status": "pending", "attempts": 0})
        if pattern.get("worth_email") and email_configured and email_state.get("status") in ("pending", "failed") and int(email_state.get("attempts", 0)) < 3:
            email_state.update({"status": "sending", "prepared_at": now, "attempts": int(email_state.get("attempts", 0)) + 1})
            count += 1
    return count


def _bark_payload(products: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    first = products[0]
    model = str(first.get("model") or "FREITAG")
    relisted = sum(1 for event in events if event.get("type") == "relisted")
    rare = [p for p in products if (p.get("pattern") or {}).get("level") == "疑似稀有"]
    label = "重新上架" if relisted == len(events) else "新品"
    if rare:
        label = f"疑似稀有 · {label}"
    title = f"FREITAG {model} {label}"
    colors = "、".join(str(p.get("primary_color") or "未标注") for p in products[:5])
    body = f"发现 {len(products)} 件：{colors}"
    if relisted:
        body += f"（{relisted} 件重新上架）"
    if len(products) == 1:
        url = str(first.get("url") or website_url())
    else:
        base = website_url()
        url = f"{base}/?view=latest&model={quote(model)}" if base else str(first.get("url") or "")
    payload: Dict[str, Any] = {
        "title": title,
        "body": body,
        "url": url,
        "group": "FREITAG WATCH",
        "level": "active",
    }
    if first.get("images"):
        payload["icon"] = first["images"][0]
    return payload


def _send_bark(payload: Mapping[str, Any]) -> None:
    key = os.environ["BARK_KEY"]
    server = os.getenv("BARK_SERVER", "https://api.day.app").rstrip("/")
    response = requests.post(
        f"{server}/push",
        json={"device_key": key, **payload},
        timeout=20,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    try:
        result = response.json()
    except ValueError:
        result = {}
    if result and int(result.get("code", 200)) != 200:
        raise RuntimeError(f"Bark 返回错误: {result}")


def deliver_bark(state: MutableMapping[str, Any], now: str) -> int:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in state.get("events", []):
        if event.get("bark", {}).get("status") == "sending":
            product = _event_product(state, event)
            grouped[str(product.get("model") or event.get("source_key"))].append(event)
    delivered = 0
    for events in grouped.values():
        products = [_event_product(state, event) for event in events]
        try:
            _send_bark(_bark_payload(products, events))
        except Exception as exc:
            for event in events:
                event["bark"].update({"status": "failed", "last_error": str(exc), "last_attempt_at": now})
        else:
            for event in events:
                event["bark"].update({"status": "sent", "sent_at": now, "last_error": None})
                delivered += 1
    return delivered


def _email_html(products: Iterable[Mapping[str, Any]]) -> str:
    cards: List[str] = []
    base = website_url()
    for product in products:
        pattern = product.get("pattern") or {}
        image = html.escape((product.get("images") or [""])[0])
        cards.append(f"""
        <div style="margin:0 0 28px;border:1px solid #ddd;padding:16px;border-radius:12px">
          <img src="{image}" alt="{html.escape(str(product.get('full_name')))}" style="width:100%;max-width:560px;height:auto;border-radius:8px">
          <h2>{html.escape(str(product.get('full_name')))} — {html.escape(str(product.get('official_item_number')))}</h2>
          <p><b>价格：</b>{product.get('price')} {html.escape(str(product.get('currency') or ''))}<br>
          <b>发现时间：</b>{html.escape(str(product.get('first_seen_at')))}<br>
          <b>类别：</b>{html.escape('、'.join(pattern.get('categories') or []))}<br>
          <b>评分：</b>{pattern.get('score')}/100（置信度 {pattern.get('confidence')}）<br>
          <b>依据：</b>{html.escape(str(pattern.get('reason') or ''))}</p>
          <p><a href="{html.escape(str(product.get('url') or ''))}">打开 FREITAG 官方购买页</a>
          {f' · <a href="{html.escape(base)}">在 FREITAG WATCH 查看</a>' if base else ''}</p>
        </div>""")
    return """<!doctype html><html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#111">
    <h1>FREITAG 特殊图案提醒</h1><p>这是自动图像规则筛选结果，不代表官方或市场对“稀有”的认定。</p>
    """ + "".join(cards) + "</body></html>"


def _send_email(products: Sequence[Mapping[str, Any]]) -> None:
    first = products[0]
    categories = "、".join((first.get("pattern") or {}).get("categories") or ["特殊图案"])
    subject = f"【FREITAG 特殊图案提醒】{first.get('full_name')} — {categories}"
    if len(products) > 1:
        subject = f"【FREITAG 特殊图案提醒】本轮发现 {len(products)} 件疑似稀有商品"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.getenv("EMAIL_FROM") or os.environ["SMTP_USERNAME"]
    message["To"] = os.environ["EMAIL_TO"]
    message.set_content("检测到疑似稀有 FREITAG 商品。请使用支持 HTML 的邮件客户端查看图片与链接。")
    message.add_alternative(_email_html(products), subtype="html")

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    security = os.getenv("SMTP_SECURITY", "ssl").lower()
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)


def deliver_email(state: MutableMapping[str, Any], now: str) -> int:
    events = [event for event in state.get("events", []) if event.get("email", {}).get("status") == "sending"]
    if not events:
        return 0
    products = [_event_product(state, event) for event in events]
    try:
        _send_email(products)
    except Exception as exc:
        for event in events:
            event["email"].update({"status": "failed", "last_error": str(exc), "last_attempt_at": now})
        return 0
    for event in events:
        event["email"].update({"status": "sent", "sent_at": now, "last_error": None})
    return len(events)


def send_bark_test() -> None:
    base = website_url() or "https://freitag.ch"
    _send_bark({
        "title": "FREITAG WATCH 测试成功",
        "body": "点击此通知测试打开链接。此消息不是新品提醒。",
        "url": base,
        "group": "FREITAG WATCH 测试",
        "level": "active",
    })


def send_email_test() -> None:
    sample = {
        "full_name": "FREITAG WATCH 邮件测试", "official_item_number": "TEST-NOT-IN-INVENTORY",
        "price": "—", "currency": "", "first_seen_at": "测试消息",
        "url": website_url() or "https://freitag.ch", "images": [],
        "pattern": {"categories": ["测试"], "score": 0, "confidence": 1,
                    "reason": "这是一封配置测试邮件，不会写入真实库存。"},
    }
    _send_email([sample])

