from __future__ import annotations

import argparse
import logging

from .analyzer import analyze_product
from .config import STATE_PATH
from .notifiers import (
    deliver_bark, deliver_email, prepare_notifications, send_bark_test, send_email_test,
)
from .runner import collect, utc_now
from .sitegen import build_public_site
from .storage import load_state, save_state


def _prepare() -> None:
    state = load_state(STATE_PATH)
    count = prepare_notifications(state, utc_now())
    save_state(STATE_PATH, state)
    print(f"已准备 {count} 个通知投递状态")


def _deliver() -> None:
    state = load_state(STATE_PATH)
    now = utc_now()
    bark = deliver_bark(state, now)
    email = deliver_email(state, now)
    save_state(STATE_PATH, state)
    print(f"Bark 已投递 {bark} 个事件；邮件已投递 {email} 个事件")


def _backfill_patterns(family: str, limit: int) -> None:
    """One-off analysis for baseline products that never got an event.

    A brand-new source is recorded as baseline without events, so its
    products never pass through the analyzer in collect(). Run once after
    adding a source family (e.g. F-ARCHIVE) to score its current stock;
    later listings are analyzed automatically by collect(). Creates no
    events and sends no notifications.
    """
    state = load_state(STATE_PATH)
    products = state.get("products", {})
    historical_hashes = [
        p.get("pattern", {}).get("perceptual_hash")
        for p in products.values()
        if isinstance(p.get("pattern"), dict) and p.get("pattern", {}).get("perceptual_hash")
    ]
    pending = [
        p for p in products.values()
        if p.get("family") == family and not isinstance(p.get("pattern"), dict)
    ]
    pending.sort(key=lambda p: p.get("first_seen_at") or "")
    if limit > 0:
        pending = pending[:limit]
    for product in pending:
        product["pattern"] = analyze_product(product, historical_hashes)
        current_hash = product.get("pattern", {}).get("perceptual_hash")
        if current_hash:
            historical_hashes.append(current_hash)
    save_state(STATE_PATH, state)
    print(f"已补分析 {len(pending)} 件 {family} 商品")


def _build() -> None:
    state = load_state(STATE_PATH)
    build_public_site(state)
    print("手机网站已生成至 public/")


def main() -> None:
    parser = argparse.ArgumentParser(prog="freitag-watch", description="FREITAG 官网公开商品监控")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect", help="采集并更新状态，不发送通知")
    sub.add_parser("prepare-notify", help="预登记待发送通知（之后应先持久化）")
    sub.add_parser("deliver-notify", help="发送已预登记通知")
    sub.add_parser("build-site", help="生成静态手机网站")
    backfill = sub.add_parser("backfill-patterns", help="一次性补分析基线商品（无事件故未分析）")
    backfill.add_argument("--family", default="F-ARCHIVE", help="只补分析该 family 的商品")
    backfill.add_argument("--limit", type=int, default=0, help="0 表示全部")
    sub.add_parser("run", help="本地完整运行（云端工作流使用更安全的分阶段命令）")
    sub.add_parser("test-bark", help="发送不写入库存的 Bark 测试通知")
    sub.add_parser("test-email", help="发送不写入库存的测试邮件")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "collect":
        print(collect())
    elif args.command == "prepare-notify":
        _prepare()
    elif args.command == "deliver-notify":
        _deliver()
    elif args.command == "build-site":
        _build()
    elif args.command == "backfill-patterns":
        _backfill_patterns(args.family, args.limit)
    elif args.command == "run":
        print(collect())
        _prepare()
        _deliver()
        _build()
    elif args.command == "test-bark":
        send_bark_test()
        print("Bark 测试通知已发送")
    elif args.command == "test-email":
        send_email_test()
        print("测试邮件已发送")


if __name__ == "__main__":
    main()

