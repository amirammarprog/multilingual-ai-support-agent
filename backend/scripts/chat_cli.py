"""Talk to the agent from the terminal, without the web UI.

    python scripts/chat_cli.py "Where is my order BC-10421?" --customer BC-C-1001
    python scripts/chat_cli.py "C'est quoi le délai de retour ?" --no-llm --debug

Several messages are sent as one conversation, so follow-up questions work.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from app.agent.service import handle_turn
from app.db import tenant_session
from app.models import Conversation, Customer, Shop
from app.tools.registry import WIDGET_SCOPES


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("messages", nargs="+")
    parser.add_argument("--shop", default="demo-shop")
    parser.add_argument("--customer", help="external ref of a demo customer, e.g. BC-C-1001")
    parser.add_argument("--no-llm", action="store_true", help="use the rule-based planner and templates only")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    async with tenant_session(None) as session:
        shop = await session.scalar(select(Shop).where(Shop.slug == args.shop))
    assert shop is not None, f"unknown shop {args.shop}"
    async with tenant_session(shop.id) as session:
        customer = None
        if args.customer:
            customer = await session.scalar(select(Customer).where(Customer.external_ref == args.customer))
        conversation = Conversation(shop_id=shop.id, customer_id=customer.id if customer else None)
        session.add(conversation)
        await session.commit()
        for text in args.messages:
            reply = await handle_turn(
                session,
                shop=shop,
                conversation_id=conversation.id,
                customer_id=customer.id if customer else None,
                text=text,
                scopes=WIDGET_SCOPES,
                use_llm=not args.no_llm,
            )
            await session.commit()
            print(f"\n> {text}\n< [{reply.language} | {reply.outcome} | {reply.latency_ms} ms] {reply.answer}")
            for s in reply.sources:
                print(f"    source {s['id']}: {s['title']} > {s['heading']} ({s['score']})")
            if args.debug:
                print(json.dumps(reply.debug, ensure_ascii=False, indent=2, default=str)[:4000])


if __name__ == "__main__":
    asyncio.run(main())
