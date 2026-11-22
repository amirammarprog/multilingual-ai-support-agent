"""Idempotent seeding of the fictional demo shops.

Shops, staff and catalogue are written with the owner connection (the application role is not
allowed to create tenants). Knowledge documents then go through the normal ingestion pipeline.
"""

from __future__ import annotations

import os
import secrets
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import (
    Customer,
    Inventory,
    KnowledgeDocument,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    Shop,
    User,
    UserRole,
)
from app.rag.embeddings import get_embedder
from app.rag.ingestion import create_document, process_document
from app.security.auth import hash_password
from app.seed import data

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
DEFAULT_DEMO_PASSWORD = "demo-password-2026"


def product_search_text(p: dict) -> str:
    return " ".join([p["sku"], p["brand"], p["category"], *p["name_i18n"].values()])


def product_embedding_text(p: dict) -> str:
    names = " / ".join(p["name_i18n"].values())
    return f"{names}. {p['description_i18n'].get('en', '')} {p['category']} {p['brand']}"


def _owner_sessionmaker() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(get_settings().migration_database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def seed_shop(session: AsyncSession, spec: dict) -> tuple[Shop, bool]:
    shop = await session.scalar(select(Shop).where(Shop.slug == spec["slug"]))
    if shop is not None:
        return shop, False
    shop = Shop(**spec, widget_secret=secrets.token_urlsafe(32))
    session.add(shop)
    await session.flush()

    password = os.environ.get("SEED_STAFF_PASSWORD") or DEFAULT_DEMO_PASSWORD
    for staff in (s for s in data.STAFF if s["shop"] == spec["slug"]):
        session.add(
            User(
                shop_id=shop.id,
                email=staff["email"],
                full_name=staff["full_name"],
                password_hash=hash_password(password),
                role=UserRole(staff["role"]),
            )
        )

    products = data.PRODUCTS[spec["slug"]]
    vectors = await get_embedder().embed_documents([product_embedding_text(p) for p in products])
    by_sku: dict[str, Product] = {}
    for p, vector in zip(products, vectors, strict=True):
        product = Product(
            shop_id=shop.id,
            sku=p["sku"],
            name_i18n=p["name_i18n"],
            description_i18n=p["description_i18n"],
            category=p["category"],
            brand=p["brand"],
            price=p["price"],
            currency=spec["currency"],
            specs=p["specs"],
            warranty_months=p["warranty_months"],
            search_text=product_search_text(p),
            embedding=vector,
        )
        session.add(product)
        await session.flush()
        by_sku[p["sku"]] = product
        session.add(
            Inventory(
                shop_id=shop.id,
                product_id=product.id,
                quantity_available=p["stock"],
                restock_date=p["restock_date"],
                low_stock_threshold=5,
            )
        )

    customers: dict[str, Customer] = {}
    for c in data.CUSTOMERS[spec["slug"]]:
        customer = Customer(shop_id=shop.id, **c)
        session.add(customer)
        customers[c["external_ref"]] = customer
    await session.flush()

    for o in data.ORDERS[spec["slug"]]:
        items = [(by_sku[sku], qty) for sku, qty in o["items"]]
        total = sum((prod.price * qty for prod, qty in items), Decimal(0))
        order = Order(
            shop_id=shop.id,
            customer_id=customers[o["customer"]].id,
            order_number=o["order_number"],
            status=OrderStatus(o["status"]),
            placed_at=o["placed_at"],
            total_amount=total,
            currency=spec["currency"],
            shipping_method=o["shipping_method"],
            carrier=o.get("carrier"),
            tracking_number=o.get("tracking_number"),
            estimated_delivery_date=o.get("estimated_delivery_date"),
            delivered_at=o.get("delivered_at"),
            shipping_city=o["shipping_city"],
            shipping_address=data.ADDRESSES[o["shipping_city"]],
        )
        session.add(order)
        await session.flush()
        for prod, qty in items:
            session.add(
                OrderItem(
                    shop_id=shop.id,
                    order_id=order.id,
                    product_id=prod.id,
                    quantity=qty,
                    unit_price=prod.price,
                )
            )
    return shop, True


async def seed_knowledge(session: AsyncSession, shop: Shop) -> list[uuid.UUID]:
    folder = KNOWLEDGE_DIR / shop.slug
    created: list[uuid.UUID] = []
    if not folder.is_dir():
        return created
    known = set(
        (await session.scalars(select(KnowledgeDocument.filename).where(KnowledgeDocument.shop_id == shop.id))).all()
    )
    for path in sorted(folder.iterdir()):
        if path.name in known or path.suffix.lower() not in {".md", ".txt", ".pdf", ".docx"}:
            continue
        doc = await create_document(session, shop.id, path.name, path.read_bytes())
        created.append(doc.id)
    return created


async def seed_all(with_knowledge: bool = True) -> None:
    factory = _owner_sessionmaker()
    pending: list[tuple[uuid.UUID, uuid.UUID]] = []
    async with factory() as session:
        for spec in data.SHOPS:
            shop, created = await seed_shop(session, spec)
            print(f"shop {shop.slug}: {'created' if created else 'already present'}")
            if with_knowledge:
                pending += [(shop.id, doc_id) for doc_id in await seed_knowledge(session, shop)]
        await session.commit()
    for shop_id, doc_id in pending:
        await process_document(shop_id, doc_id)
    if pending:
        print(f"indexed {len(pending)} knowledge documents")
    async with factory() as session:
        docs = (
            await session.execute(
                select(KnowledgeDocument.filename, KnowledgeDocument.status, KnowledgeDocument.chunk_count)
            )
        ).all()
        for filename, status, chunks in docs:
            print(f"  {filename}: {status.value} ({chunks} chunks)")


async def create_staff(shop_slug: str, email: str, name: str, role: str, password: str) -> None:
    if len(password) < 12:
        raise SystemExit("password must be at least 12 characters")
    factory = _owner_sessionmaker()
    async with factory() as session:
        shop = await session.scalar(select(Shop).where(Shop.slug == shop_slug))
        if shop is None:
            raise SystemExit(f"unknown shop {shop_slug}")
        session.add(
            User(
                shop_id=shop.id,
                email=email.lower(),
                full_name=name,
                password_hash=hash_password(password),
                role=UserRole(role),
            )
        )
        await session.commit()
    print(f"created {role} {email} for {shop_slug}")
