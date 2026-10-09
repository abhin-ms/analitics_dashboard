#!/usr/bin/env python3
"""Seed script: creates all roles, permissions, users, stores, currencies, KPIs, bands."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import AsyncSessionLocal, engine
from app.db.base import Base
from app.core.security import hash_password
from app.models.models import (
    Role, Permission, RolePermission, User, UserStoreAccess,
    Store, Currency, KPIWeight, IncentiveBand, Setting,
)
from app.instagram.models import (
    AIProvider, IGAccount, IGConversation, IGMessage,
    IGComment, IGCommentRule, AIUsageLog, IGFAQ, IGBotSettings,
)
from app.instagram.form_models import IGForm, IGFormField, IGFormSubmission
from sqlalchemy import select

RESOURCES = [
    "dashboard", "operations", "investments", "team_leaders",
    "leads", "campaigns", "tasks", "performance", "reports",
    "users", "roles", "settings", "sheet_sync", "instagram",
    "ai_analytics",
    # one per menu page that used to borrow another page's permission
    "store_overview", "social_performance", "stock_position", "country_comparison",
    "sales_reports", "sheet_assignments",
]
COMPANY_PAGES = {"store_overview": {"view"}, "social_performance": {"view"}, "stock_position": {"view"},
                 "country_comparison": {"view"}, "sales_reports": {"view"}, "sheet_assignments": {"view"}}
ACTIONS = ["view", "create", "edit", "delete", "export", "manage"]

ROLE_PERMISSIONS = {
    "SuperAdmin": {r: set(ACTIONS) for r in RESOURCES},
    "Admin": {r: set(ACTIONS) for r in RESOURCES},
    "CEO": {
        "dashboard": {"view"}, "team_leaders": {"view"},
        "operations": {"view"}, "leads": {"view"}, "campaigns": {"view"},
        "tasks": {"view"}, "performance": {"view", "edit", "export"},
        "reports": {"view", "export"}, "investments": {"view"},
        "instagram": {"view"}, "ai_analytics": {"view", "manage"},
        "users": {"view", "create"}, **COMPANY_PAGES,
    },
    "COO": {
        "dashboard": {"view"}, "team_leaders": {"view", "edit"},
        "operations": {"view"}, "leads": {"view"}, "campaigns": {"view"},
        "tasks": {"view"}, "performance": {"view", "edit", "export"},
        "reports": {"view", "export"}, "investments": {"view"},
        "instagram": {"view", "edit"}, "ai_analytics": {"view"}, **COMPANY_PAGES,
    },
    "Regional Manager": {
        "dashboard": {"view"}, "team_leaders": {"view", "edit"},
        "operations": {"view", "edit"}, "leads": {"view", "edit"},
        "campaigns": {"view"}, "tasks": {"view", "edit"},
        "performance": {"view"}, "reports": {"view"},
        "instagram": {"view"}, **COMPANY_PAGES,
    },
    # Pages each role sees are exactly its View ticks; a team leader's
    # figures are always limited to the stores they lead.
    "Team Leader": {
        "dashboard": {"view"},
        "operations": {"edit"}, "leads": {"view", "create", "edit"},
        "campaigns": {"view"}, "tasks": {"view", "create", "edit"},
        "social_performance": {"view"},
    },
    "Store Staff": {
        "dashboard": {"view"}, "operations": {"create"},
        "leads": {"view", "create"}, "tasks": {"view"}, "social_performance": {"view"},
    },
    "Store Owner": {
        "dashboard": {"view"}, "social_performance": {"view"},
    },
    "Telecaller": {
        "dashboard": {"view"}, "leads": {"view", "create", "edit"},
    },
    "Salesperson": {
        "dashboard": {"view"}, "leads": {"view", "create", "edit"},
        "operations": {"view", "create"}, "tasks": {"view", "create"},
    },
    "Viewer": {
        "dashboard": {"view"}, "operations": {"view"},
        "team_leaders": {"view"}, "leads": {"view"},
        "campaigns": {"view"}, "tasks": {"view"},
        "performance": {"view"}, "reports": {"view"},
        "instagram": {"view"}, **COMPANY_PAGES,
    },
}

STORES = [
    ("Kerala Kochi", "Harsh", 26667, 800000, "Kerala"),
    ("Kerala Trivandrum", "Sam", 16667, 500000, "Kerala"),
    ("Kerala Thrissur", "Michael", 10833, 325000, "Kerala"),
    ("Kerala Kannur", "Michael", 8333, 250000, "Kerala"),
    ("Kerala Calicut", "Harsh", 20000, 600000, "Kerala"),
    ("Mumbai Korum", "Abdullah", 6667, 200000, "Maharashtra"),
    ("Bangalore Marathahalli", "Vishnu", 10833, 325000, "Karnataka"),
    ("Mangalore", "Vishnu", 11667, 350000, "Karnataka"),
    ("Bangalore Indiranagar", "Nazil", 30000, 900000, "Karnataka"),
    ("Chennai Kodambakam", "Sam", 20000, 600000, "Tamil Nadu"),
    ("Chennai Velachery", "Sam", 13333, 400000, "Tamil Nadu"),
    ("Mumbai Bandra", "Abdullah", 6667, 200000, "Maharashtra"),
    ("Kerala Palakkad", "Michael", 11667, 350000, "Kerala"),
    ("Delhi Lajpat Nagar", "Abdullah", 8333, 250000, "Delhi"),
    ("Guwahati", "Michael", 8333, 250000, "Assam"),
    ("Kerala Pathanamthitta", "Michael", 8333, 250000, "Kerala"),
    ("Hyderabad Kukatpally", "Abdullah", 20000, 600000, "Telangana"),
    ("Hyderabad Hitech", "Abdullah", 20000, 600000, "Telangana"),
    ("Tn Coimbatore", "Sam", 16667, 500000, "Tamil Nadu"),
    ("Kerala Kasargod", "Michael", 10833, 325000, "Kerala"),
    ("Kerala Kollam", "Sam", 8333, 250000, "Kerala"),
    ("Mysore", "Vishnu", 9167, 275000, "Karnataka"),
    ("Kerala Kottkal", "Harsh", 18333, 550000, "Kerala"),
    ("Kerala Wayanad", "Harsh", 10000, 300000, "Kerala"),
    ("Guwahati Store", "Guwahati", 15000, 450000, "Assam"),
    ("Delhi Store", "Delhi", 20000, 600000, "Delhi"),
    ("Kerala Store", "Kerala", 18000, 540000, "Kerala"),
    ("Chennai Store", "Chennai", 16667, 500000, "Tamil Nadu"),
    ("Mumbai Store", "Mumbai", 20000, 600000, "Maharashtra"),
]

KPI_WEIGHTS = [
    ("Revenue vs Target", "Revenue achievement against monthly target", 0.30),
    ("DSR Submission Rate", "Daily submission completeness", 0.10),
    ("Walk-in Conversion", "Walk-in to sale conversion rate", 0.10),
    ("Cash Management", "Cash reconciliation accuracy", 0.10),
    ("Care+ Attachment Rate", "Care+ product attachment (TBD weight)", 0.00),
    ("Calls vs Target", "Outbound calls against daily target", 0.10),
    ("Stock Control", "Stock variance minimization", 0.10),
    ("Training Compliance", "Training completion rate", 0.05),
    ("BP App Update Rate", "BP app update compliance", 0.05),
    ("Complaint Resolution", "Complaint resolution rate", 0.10),
]

INCENTIVE_BANDS = [
    ("Star", 1.10, 1.40, "140% Star"),
    ("Above Target", 1.00, 1.20, "120% Accelerated"),
    ("On Target", 0.90, 1.00, "100% Full Pay"),
    ("Below Target", 0.00, 1.00, "Below Target - TBD, confirm with Abhin"),
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Check if already seeded
        existing = await db.execute(select(Role))
        if existing.scalars().first():
            print("Already seeded. Skipping.")
            return

        # 1. Currencies
        currencies = [
            Currency(code="INR", name="Indian Rupee", symbol="\u20b9", decimal_places=2, number_format_style="indian"),
            Currency(code="USD", name="US Dollar", symbol="$", decimal_places=2, number_format_style="western"),
            Currency(code="GBP", name="British Pound", symbol="\u00a3", decimal_places=2, number_format_style="western"),
            Currency(code="AED", name="UAE Dirham", symbol="AED", decimal_places=2, number_format_style="western"),
            Currency(code="EUR", name="Euro", symbol="\u20ac", decimal_places=2, number_format_style="western"),
        ]
        db.add_all(currencies)
        await db.flush()
        print(f"  Created {len(currencies)} currencies")

        # 2. Roles
        role_objs = {}
        for name in ROLE_PERMISSIONS:
            role = Role(name=name, description=f"{name} role")
            db.add(role)
            await db.flush()
            role_objs[name] = role
        print(f"  Created {len(role_objs)} roles")

        # 3. Permissions + role_permissions
        perm_objs = {}
        for res in RESOURCES:
            for act in ACTIONS:
                perm = Permission(resource=res, action=act)
                db.add(perm)
                await db.flush()
                perm_objs[(res, act)] = perm

        for role_name, perms_map in ROLE_PERMISSIONS.items():
            role = role_objs[role_name]
            for res, acts in perms_map.items():
                for act in acts:
                    perm = perm_objs.get((res, act))
                    if perm:
                        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
        await db.flush()
        print(f"  Created {len(perm_objs)} permissions + role assignments")

        # 4. SuperAdmin user
        admin = User(
            name="SuperAdmin",
            email="admin@breakprotection.com",
            password_hash=hash_password("admin123"),
            role_id=role_objs["SuperAdmin"].id,
            is_active=True,
        )
        db.add(admin)
        await db.flush()
        print("  Created SuperAdmin (admin@breakprotection.com / admin123)")

        # COO
        coo = User(
            name="COO",
            email="coo@breakprotection.com",
            password_hash=hash_password("coo123"),
            role_id=role_objs["COO"].id,
            is_active=True,
        )
        db.add(coo)
        await db.flush()
        print("  Created COO (coo@breakprotection.com / coo123)")

        # 5. "Unassigned" placeholder team leader — stores need a non-null
        # team_leader_id at creation time, but real team leaders are meant to
        # be created by an admin (Settings > Users) and assigned to branches
        # (Settings > Team Leaders & Branches) after seeding, not seeded as
        # fake demo people.
        unassigned_tl = User(
            name="Unassigned",
            email="unassigned@system.local",
            password_hash=hash_password("not-a-real-login"),
            role_id=role_objs["Team Leader"].id,
            is_active=False,
        )
        db.add(unassigned_tl)
        await db.flush()
        print("  Created 'Unassigned' placeholder team leader")

        # 6. Stores (all start owned by the placeholder TL above until an
        # admin assigns a real team leader to each one)
        store_objs = {}
        for store_name, _tl_name, daily, monthly, region in STORES:
            store = Store(
                name=store_name,
                team_leader_id=unassigned_tl.id,
                currency_code="INR",
                daily_target=daily,
                monthly_target=monthly,
                region=region,
            )
            db.add(store)
            await db.flush()
            store_objs[store_name] = store
        await db.flush()
        print(f"  Created {len(store_objs)} stores (owned by 'Unassigned' until assigned)")

        # 6b. Salespersons (1 per city-based TL)
        salesperson_data = [
            ("Ravi", "ravi@breakprotection.com", "Guwahati"),
            ("Amit", "amit@breakprotection.com", "Delhi"),
            ("Priya", "priya@breakprotection.com", "Kerala"),
            ("Deepak", "deepak@breakprotection.com", "Chennai"),
            ("Rohit", "rohit@breakprotection.com", "Mumbai"),
        ]
        sp_role = role_objs["Salesperson"]
        sp_users = {}
        for sp_name, sp_email, sp_tl in salesperson_data:
            user = User(
                name=sp_name,
                email=sp_email,
                password_hash=hash_password(f"{sp_name.lower()}123"),
                role_id=sp_role.id,
                is_active=True,
            )
            db.add(user)
            await db.flush()
            sp_users[sp_name] = user
            # Grant access to their TL's store
            store_name = f"{sp_tl} Store"
            if store_name in store_objs:
                db.add(UserStoreAccess(user_id=user.id, store_id=store_objs[store_name].id))
        await db.flush()
        print(f"  Created {len(sp_users)} Salespersons")

        # Telecallers are no longer seeded as fake demo people — create real
        # ones via Settings > Users (or have a Team Leader create one from
        # the Leads Update page), then assign them to a city sheet via
        # Settings > Sheet Assignments.

        # 7. KPI Weights
        for name, desc, weight in KPI_WEIGHTS:
            db.add(KPIWeight(kpi_name=name, description=desc, weight=weight))
        print(f"  Created {len(KPI_WEIGHTS)} KPI weights")

        # 8. Incentive Bands
        for name, min_score, multiplier, label in INCENTIVE_BANDS:
            db.add(IncentiveBand(band_name=name, min_kpi_score=min_score, multiplier=multiplier, label=label))
        print(f"  Created {len(INCENTIVE_BANDS)} incentive bands")

        # 9. Settings
        db.add(Setting(key="base_reporting_currency", value="INR"))
        db.add(Setting(key="same_day_edit_window_hours", value="12"))
        print("  Created settings")

        # 10. AI Providers (inactive by default)
        db.add(AIProvider(provider="claude", api_key_encrypted="NOT_CONFIGURED", model_name="claude-sonnet-4-6", is_active=False))
        db.add(AIProvider(provider="openai", api_key_encrypted="NOT_CONFIGURED", model_name="gpt-4o", is_active=False))
        print("  Created AI providers (Claude + OpenAI, inactive)")

        await db.commit()
        print("\nSeed complete!")


if __name__ == "__main__":
    asyncio.run(seed())
