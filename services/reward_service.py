"""SAXAZ Anti-Farming Reward Coin Wallet, Shop & Adaptive Question Memory Service.

Conversion Anchor:
  - 5,000 Coins = Rs 50 INR (100 Coins = Rs 1.00 INR, 1 Coin = Rs 0.01)

Anti-Farming Design:
  - Every reward has a deterministic canonical `reward_key` enforced by
    `UNIQUE(student_id, reward_key)` in SQLite `coin_ledger`, union-merged with
    per-user Vercel Blob (`saxaz_wallet_{uid}.json`) and an HMAC-signed
    `saxaz_wallet` cookie so neither repeating activities/exams nor cold
    serverless restarts can ever double-award a milestone.
  - Per-chapter hard ceiling = 200 Coins (Rs 2.00):
      * Chapter in a Nutshell:        +10 Coins (1x per chapter)
      * Chapter Summary Videos (4x):   +5 Coins each = +20 Coins (1x per video)
      * Heart Activity Stage 1 & 2:   +15 + +25 = +40 Coins (1x per chapter)
      * Let's Discuss Prompts (2x):   +10 each = +20 Coins (1x per prompt)
      * Mock Exam Pass (>=50%) + Ace (>=85%): +30 + +10 = +40 Coins (1x per paper)
      * Real Exam Tiers (50%/75%/90%): +30 + +20 + +20 = +70 Coins (1x per tier)
"""

from __future__ import annotations

import os
import re
import secrets
import time
from typing import Optional

from fastapi import Request, Response
import security

COINS_PER_INR = 100  # 5,000 Coins = Rs 50 INR

SHOP_ITEMS = [
    {
        "code": "book_science_atlas",
        "title": "3D Illustrated Science Atlas",
        "subtitle": "Full-color visual cutaway guide to Earth, Physics, Atoms, and Living Systems for Class 10.",
        "cost_coins": 5000,
        "inr_value": 50,
        "prefix": "BKATL50",
        "category": "Play Books E-Book",
        "kind": "ebook",
        "tab": "books",
        "author": "SAXAZ Science Press",
        "rating": "4.9",
        "reviews": "2.4k",
        "pages_or_tag": "128 Pages · Visual E-Book",
        "badge": "Editor's Choice",
        "image": "/static/images/saxaz_web/store/book_science_atlas.webp",
        "highlights": [
            "60+ high-resolution 3D cutaway diagrams across Physics, Chemistry & Biology",
            "Quick-scan formula & concept maps at the end of every chapter",
            "Instant digital unlock code for SAXAZ Reader & printable study sheets",
        ],
    },
    {
        "code": "book_biology_comic",
        "title": "Life Processes Visual Comic Guide",
        "subtitle": "Story-driven comic handbook covering Nutrition, Respiration, Heart Circulation & Excretion.",
        "cost_coins": 5000,
        "inr_value": 50,
        "prefix": "BKBIO50",
        "category": "Play Books Comic",
        "kind": "ebook",
        "tab": "books",
        "author": "SAXAZ Visual Studio",
        "rating": "5.0",
        "reviews": "3.1k",
        "pages_or_tag": "96 Pages · Illustrated Comic",
        "badge": "Top Selling",
        "image": "/static/images/saxaz_web/store/book_biology_comic.webp",
        "highlights": [
            "Step-by-step illustrated comic panels for every Class 10 Biology diagram",
            "Memory mnemonics for Double Circulation, Nephron Filtration & Photosynthesis",
            "Includes 50 solved board-style viva & diagram-labelling checkpoints",
        ],
    },
    {
        "code": "book_maths_playbook",
        "title": "Class 10 Maths Formula Playbook",
        "subtitle": "Pocket-ready theorem, trigonometry, coordinate geometry & shortcut handbook.",
        "cost_coins": 5000,
        "inr_value": 50,
        "prefix": "BKMTH50",
        "category": "Play Books Guide",
        "kind": "ebook",
        "tab": "books",
        "author": "SAXAZ Maths Lab",
        "rating": "4.8",
        "reviews": "1.9k",
        "pages_or_tag": "112 Pages · Formula Handbook",
        "badge": "Exam Booster",
        "image": "/static/images/saxaz_web/store/book_maths_playbook.webp",
        "highlights": [
            "Every Class 10 theorem, proof structure & identity on single-glance cards",
            "Common board-exam step-marking traps highlighted with worked examples",
            "Speed-check mental calculation tricks for MCQs and case-study problems",
        ],
    },
    {
        "code": "book_board_special",
        "title": "Board Topper 100 Solved Papers",
        "subtitle": "Model answer scripts, marking-scheme breakdowns & time-management blueprints.",
        "cost_coins": 5000,
        "inr_value": 50,
        "prefix": "BKTOP50",
        "category": "Play Books Prep",
        "kind": "ebook",
        "tab": "books",
        "author": "SAXAZ Academic Board",
        "rating": "4.9",
        "reviews": "2.8k",
        "pages_or_tag": "164 Pages · Solved Bank",
        "badge": "Board Special",
        "image": "/static/images/saxaz_web/store/book_board_special.webp",
        "highlights": [
            "Examiner-graded topper answer layouts showing how to score full marks",
            "Chapter-wise high-weightage HOTS, assertion-reason & competency questions",
            "40-minute & 3-hour exam pacing checklists ready for revision week",
        ],
    },
    {
        "code": "stationery_pack_50",
        "title": "Exam Geometry & Pen Set Voucher",
        "subtitle": "Redeemable for Rs 50 precision geometry box & smooth exam gel-pen kit in the SAXAZ Store.",
        "cost_coins": 5000,
        "inr_value": 50,
        "prefix": "KIT50",
        "category": "Study Gear",
        "kind": "store",
        "tab": "gear",
        "author": "SAXAZ Gear Studio",
        "rating": "4.9",
        "reviews": "1.6k",
        "pages_or_tag": "Physical Kit Voucher · Rs 50",
        "badge": "Student Favorite",
        "image": "/static/images/saxaz_web/store/item_geometry_kit.webp",
        "highlights": [
            "Precision metal compass, divider, crystal-clear protractor & set-squares",
            "5 smudge-free fast-dry exam pens built for neat diagram labelling",
            "Redeemable at checkout on saxaz.com with your instant voucher code",
        ],
    },
    {
        "code": "science_kit_100",
        "title": "Rs 100 Science Explorer Lab Voucher",
        "subtitle": "Double-milestone reward for hands-on pocket microscope, prisms & experiment kits.",
        "cost_coins": 10000,
        "inr_value": 100,
        "prefix": "LAB100",
        "category": "Premium Lab Kit",
        "kind": "store",
        "tab": "gear",
        "author": "SAXAZ STEM Labs",
        "rating": "5.0",
        "reviews": "1.2k",
        "pages_or_tag": "STEM Kit Credit · Rs 100",
        "badge": "Premium Reward",
        "image": "/static/images/saxaz_web/store/item_science_kit.webp",
        "highlights": [
            "Applies Rs 100 off any SAXAZ hands-on Science Explorer Kit or lab bundle",
            "Includes optics prism, slide-prep accessories & magnet experiment guide",
            "Stackable milestone reward for dedicated Science & Biology champions",
        ],
    },
    {
        "code": "saxaz_sub_50",
        "title": "Rs 50 SAXAZ Subscription Discount",
        "subtitle": "Apply Rs 50 off your next SAXAZ issue or annual All-Access learning pass renewal.",
        "cost_coins": 5000,
        "inr_value": 50,
        "prefix": "SXZ50",
        "category": "Subscription Pass",
        "kind": "store",
        "tab": "passes",
        "author": "SAXAZ Membership",
        "rating": "4.9",
        "reviews": "4.2k",
        "pages_or_tag": "Instant Pass Credit · Rs 50",
        "badge": "VIP Pass",
        "image": "/static/images/saxaz_web/store/item_sub_pass.webp",
        "highlights": [
            "Instant Rs 50 discount code valid on monthly issues or annual renewals",
            "Unlocks uninterrupted access to AI Voice Tutors, Mock Exams & Real Exams",
            "Share directly with your parent to apply at saxaz.com checkout",
        ],
    },
    {
        "code": "saxaz_store_50",
        "title": "Rs 50 SAXAZ Store Voucher",
        "subtitle": "Universal Rs 50 store gift card valid on any book, stationery pack, or issue in SAXAZ Shop.",
        "cost_coins": 5000,
        "inr_value": 50,
        "prefix": "SHOP50",
        "category": "Store Credit",
        "kind": "store",
        "tab": "passes",
        "author": "SAXAZ Student Shop",
        "rating": "4.9",
        "reviews": "3.7k",
        "pages_or_tag": "All-Store Gift Card · Rs 50",
        "badge": "Best Value",
        "image": "/static/images/saxaz_web/store/item_gift_voucher.webp",
        "highlights": [
            "Works across the entire SAXAZ catalog with zero category restrictions",
            "Generated atomically with a unique SHOP50 voucher code you can copy anytime",
            "Never expires while your student account remains active",
        ],
    },
]

SHOP_ITEMS_BY_CODE = {item["code"]: item for item in SHOP_ITEMS}

# Strict server-side whitelist of interactive milestone claim keys -> (coins, label_template)
_CLAIM_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    (re.compile(r"^nutshell:ch:(\d+)$"), 10, "Completed Chapter in a Nutshell (Chapter #{0})"),
    (re.compile(r"^heart_s1:ch:(\d+)$"), 15, "Assembled the Human Heart Chambers (Stage 1)"),
    (re.compile(r"^heart_s2:ch:(\d+)$"), 25, "Mastered Double Circulation Pump (Stage 2)"),
    (re.compile(r"^discuss:ch:(\d+):q([12])$"), 10, "Completed Let's Discuss Checkpoint #{1}"),
    (re.compile(r"^game:ch:(\d+):(leaf|food|breathe|blood|pump|kidney|team)$"), 5, "Won a summary mini-game ({1})"),
]

_WALLET_BLOB_TTL = 12.0
_LAST_WALLET_BLOB_READ: dict[int, float] = {}


def _ensure_tables(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coin_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            reward_key TEXT NOT NULL,
            coins INTEGER NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, reward_key)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coin_redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            item_code TEXT NOT NULL,
            item_title TEXT NOT NULL,
            coins_spent INTEGER NOT NULL,
            inr_value INTEGER NOT NULL,
            coupon_code TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _wallet_blob_key(student_id: int) -> str:
    return f"saxaz_wallet_u{int(student_id)}.json"


def coins_to_inr(coins: int) -> float:
    return round(max(0, int(coins or 0)) / float(COINS_PER_INR), 2)


def recompute_coin_balance(conn, student_id: int) -> int:
    _ensure_tables(conn)
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(coins), 0) FROM coin_ledger WHERE student_id = ?", (student_id,))
    earned = int(c.fetchone()[0] or 0)
    c.execute("SELECT COALESCE(SUM(coins_spent), 0) FROM coin_redemptions WHERE student_id = ?", (student_id,))
    spent = int(c.fetchone()[0] or 0)
    bal = max(0, earned - spent)
    try:
        c.execute("UPDATE users SET coin_balance = ? WHERE id = ?", (bal, student_id))
        conn.commit()
    except Exception:
        pass
    return bal


def export_wallet_snapshot(conn, student_id: int, extra_qmem: Optional[dict] = None) -> dict:
    _ensure_tables(conn)
    c = conn.cursor()
    c.execute(
        "SELECT reward_key, coins, label, created_at FROM coin_ledger WHERE student_id = ? ORDER BY id ASC",
        (student_id,),
    )
    ledger = [
        {"k": r[0], "c": int(r[1]), "l": r[2], "t": r[3] or ""}
        for r in c.fetchall()
    ]
    c.execute(
        "SELECT item_code, item_title, coins_spent, inr_value, coupon_code, created_at FROM coin_redemptions WHERE student_id = ? ORDER BY id ASC",
        (student_id,),
    )
    redemptions = [
        {"ic": r[0], "it": r[1], "cs": int(r[2]), "inr": int(r[3]), "cp": r[4], "t": r[5] or ""}
        for r in c.fetchall()
    ]
    snap = {
        "uid": int(student_id),
        "ledger": ledger[-120:],
        "redemptions": redemptions[-40:],
    }
    if extra_qmem:
        snap["qmem"] = extra_qmem
    return snap


def _merge_snapshot_into_db(conn, student_id: int, snap: Optional[dict]) -> None:
    if not isinstance(snap, dict) or int(snap.get("uid") or -1) != int(student_id):
        return
    _ensure_tables(conn)
    c = conn.cursor()
    changed = False
    for entry in (snap.get("ledger") or []):
        if not isinstance(entry, dict) or not entry.get("k"):
            continue
        c.execute(
            "INSERT OR IGNORE INTO coin_ledger (student_id, reward_key, coins, label, created_at) VALUES (?, ?, ?, ?, COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP))",
            (student_id, str(entry["k"]), int(entry.get("c") or 0), str(entry.get("l") or "Milestone"), str(entry.get("t") or "")),
        )
        if c.rowcount:
            changed = True
    for red in (snap.get("redemptions") or []):
        if not isinstance(red, dict) or not red.get("cp"):
            continue
        c.execute("SELECT 1 FROM coin_redemptions WHERE student_id = ? AND coupon_code = ?", (student_id, str(red["cp"])))
        if not c.fetchone():
            c.execute(
                "INSERT INTO coin_redemptions (student_id, item_code, item_title, coins_spent, inr_value, coupon_code, created_at) VALUES (?, ?, ?, ?, ?, ?, COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP))",
                (
                    student_id,
                    str(red.get("ic") or "item"),
                    str(red.get("it") or "Reward"),
                    int(red.get("cs") or 5000),
                    int(red.get("inr") or 50),
                    str(red["cp"]),
                    str(red.get("t") or ""),
                ),
            )
            changed = True
    if changed:
        conn.commit()


def hydrate_student_wallet(request: Optional[Request], conn, user: dict, force_blob: bool = False) -> int:
    """Hydrate wallet ledger & redemptions from signed cookie + Vercel Blob, then update user['coin_balance']."""
    if not user or user.get("role") != "student" or user.get("is_parent"):
        return 0
    uid = int(user["id"])
    _ensure_tables(conn)

    if request is not None:
        raw_cookie = request.cookies.get("saxaz_wallet")
        if raw_cookie:
            cookie_snap = security.decode_signed_json(raw_cookie, "w1")
            _merge_snapshot_into_db(conn, uid, cookie_snap)

    now = time.time()
    if force_blob or (now - _LAST_WALLET_BLOB_READ.get(uid, 0.0)) > _WALLET_BLOB_TTL:
        _LAST_WALLET_BLOB_READ[uid] = now
        blob_snap = security._get_blob_json(_wallet_blob_key(uid))
        if isinstance(blob_snap, dict):
            _merge_snapshot_into_db(conn, uid, blob_snap)

    bal = recompute_coin_balance(conn, uid)
    user["coin_balance"] = bal
    user["coin_inr"] = coins_to_inr(bal)
    return bal


def persist_wallet(conn, student_id: int, response: Optional[Response] = None, request: Optional[Request] = None, qmem_override: Optional[dict] = None) -> dict:
    existing_qmem = qmem_override
    if existing_qmem is None and request is not None:
        raw_cookie = request.cookies.get("saxaz_wallet")
        if raw_cookie:
            ck = security.decode_signed_json(raw_cookie, "w1")
            if isinstance(ck, dict) and int(ck.get("uid") or -1) == int(student_id):
                existing_qmem = ck.get("qmem")
    snap = export_wallet_snapshot(conn, student_id, extra_qmem=existing_qmem)
    try:
        security._put_blob_json(_wallet_blob_key(student_id), snap)
    except Exception:
        pass
    if response is not None:
        is_prod = os.environ.get("K_SERVICE") is not None or bool(os.environ.get("VERCEL"))
        # Keep cookie compact (last 60 ledger keys + last 20 redemptions + compact qmem)
        compact_snap = {
            "uid": int(student_id),
            "ledger": snap["ledger"][-60:],
            "redemptions": snap["redemptions"][-20:],
        }
        if existing_qmem:
            compact_snap["qmem"] = existing_qmem
        tok = security.encode_signed_json("w1", compact_snap)
        response.set_cookie(
            key="saxaz_wallet",
            value=tok,
            httponly=True,
            max_age=365 * 24 * 60 * 60,
            samesite="lax",
            secure=is_prod,
        )
    return snap


def award_milestone_coins(
    conn,
    student_id: int,
    reward_key: str,
    coins: int,
    label: str,
    request: Optional[Request] = None,
    response: Optional[Response] = None,
) -> dict:
    """Idempotently award fixed one-time coins for `reward_key`. Never double-awards."""
    _ensure_tables(conn)
    if request is not None:
        raw_cookie = request.cookies.get("saxaz_wallet")
        if raw_cookie:
            _merge_snapshot_into_db(conn, student_id, security.decode_signed_json(raw_cookie, "w1"))

    clean_key = str(reward_key or "").strip()
    pts = max(0, int(coins or 0))
    if not clean_key or pts <= 0:
        bal = recompute_coin_balance(conn, student_id)
        return {"awarded": False, "already_claimed": True, "coins_added": 0, "coin_balance": bal, "inr_value": coins_to_inr(bal), "label": label}

    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO coin_ledger (student_id, reward_key, coins, label) VALUES (?, ?, ?, ?)",
        (student_id, clean_key, pts, str(label or clean_key)),
    )
    was_inserted = c.rowcount == 1
    conn.commit()
    bal = recompute_coin_balance(conn, student_id)
    if was_inserted or response is not None:
        persist_wallet(conn, student_id, response=response, request=request)
    return {
        "awarded": was_inserted,
        "already_claimed": not was_inserted,
        "coins_added": pts if was_inserted else 0,
        "coin_balance": bal,
        "inr_value": coins_to_inr(bal),
        "reward_key": clean_key,
        "label": label,
    }


def claim_whitelisted_milestone(
    conn,
    student_id: int,
    reward_key: str,
    request: Optional[Request] = None,
    response: Optional[Response] = None,
) -> dict:
    """Validate `reward_key` against strict server-side patterns so clients can never invent coin amounts."""
    clean_key = str(reward_key or "").strip()
    for pat, fixed_coins, lbl_tpl in _CLAIM_PATTERNS:
        m = pat.match(clean_key)
        if m:
            lbl = lbl_tpl.format(*m.groups())
            return award_milestone_coins(conn, student_id, clean_key, fixed_coins, lbl, request=request, response=response)
    bal = recompute_coin_balance(conn, student_id)
    return {
        "awarded": False,
        "error": "Invalid milestone key",
        "coins_added": 0,
        "coin_balance": bal,
        "inr_value": coins_to_inr(bal),
    }


def award_exam_completion_coins(
    conn,
    student_id: int,
    exam_paper_id: int,
    exam_type: str,
    pct_score: float,
    status: str = "completed",
    paper_title: str = "Exam",
    request: Optional[Request] = None,
    response: Optional[Response] = None,
) -> dict:
    """Award fixed one-time bracket coins for completing a Mock or Real Exam.

    Retaking an exam at the same or lower score awards 0 coins.
    Improving to a higher bracket awards ONLY the newly unlocked bracket delta.
    """
    _ensure_tables(conn)
    if status != "completed" or pct_score < 50.0:
        bal = recompute_coin_balance(conn, student_id)
        return {"awarded": False, "coins_added": 0, "coin_balance": bal, "inr_value": coins_to_inr(bal), "unlocked_labels": []}

    tiers: list[tuple[str, int, str]] = []
    clean_title = str(paper_title or f"Exam #{exam_paper_id}")[:60]
    if str(exam_type or "mock").lower() == "real":
        if pct_score >= 50.0:
            tiers.append((f"real_tier1:paper:{exam_paper_id}", 30, f"Completed Official Real Exam (50%+) — {clean_title}"))
        if pct_score >= 75.0:
            tiers.append((f"real_tier2:paper:{exam_paper_id}", 20, f"High Score Tier (75%+) — {clean_title}"))
        if pct_score >= 90.0:
            tiers.append((f"real_tier3:paper:{exam_paper_id}", 20, f"Distinction Tier (90%+) — {clean_title}"))
    else:
        if pct_score >= 50.0:
            tiers.append((f"mock_pass:paper:{exam_paper_id}", 30, f"Passed Mock Exam (50%+) — {clean_title}"))
        if pct_score >= 85.0:
            tiers.append((f"mock_ace:paper:{exam_paper_id}", 10, f"85%+ Mastery Bonus — {clean_title}"))

    total_added = 0
    unlocked_labels: list[str] = []
    for r_key, r_coins, r_lbl in tiers:
        res = award_milestone_coins(conn, student_id, r_key, r_coins, r_lbl, request=request, response=None)
        if res.get("awarded"):
            total_added += int(res.get("coins_added") or 0)
            unlocked_labels.append(r_lbl)

    bal = recompute_coin_balance(conn, student_id)
    if total_added > 0 or response is not None:
        persist_wallet(conn, student_id, response=response, request=request)
    return {
        "awarded": total_added > 0,
        "coins_added": total_added,
        "coin_balance": bal,
        "inr_value": coins_to_inr(bal),
        "unlocked_labels": unlocked_labels,
    }


def get_claimed_keys(conn, student_id: int) -> set[str]:
    _ensure_tables(conn)
    rows = conn.execute("SELECT reward_key FROM coin_ledger WHERE student_id = ?", (student_id,)).fetchall()
    return {str(r[0]) for r in rows}


def get_wallet_details(conn, student_id: int) -> dict:
    _ensure_tables(conn)
    bal = recompute_coin_balance(conn, student_id)
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(coins), 0) FROM coin_ledger WHERE student_id = ?", (student_id,))
    lifetime_earned = int(c.fetchone()[0] or 0)
    c.execute("SELECT COALESCE(SUM(coins_spent), 0) FROM coin_redemptions WHERE student_id = ?", (student_id,))
    lifetime_spent = int(c.fetchone()[0] or 0)

    c.execute(
        "SELECT reward_key, coins, label, created_at FROM coin_ledger WHERE student_id = ? ORDER BY id DESC LIMIT 30",
        (student_id,),
    )
    ledger_rows = [
        {"reward_key": r[0], "coins": int(r[1]), "label": r[2], "created_at": (r[3] or "")[:16]}
        for r in c.fetchall()
    ]

    c.execute(
        "SELECT id, item_code, item_title, coins_spent, inr_value, coupon_code, created_at FROM coin_redemptions WHERE student_id = ? ORDER BY id DESC LIMIT 20",
        (student_id,),
    )
    redemptions = [
        {
            "id": r[0],
            "item_code": r[1],
            "item_title": r[2],
            "coins_spent": int(r[3]),
            "inr_value": int(r[4]),
            "coupon_code": r[5],
            "created_at": (r[6] or "")[:16],
        }
        for r in c.fetchall()
    ]

    claimed = get_claimed_keys(conn, student_id)
    return {
        "coin_balance": bal,
        "inr_value": coins_to_inr(bal),
        "lifetime_earned": lifetime_earned,
        "lifetime_spent": lifetime_spent,
        "ledger": ledger_rows,
        "redemptions": redemptions,
        "claimed_keys": claimed,
        "shop_items": SHOP_ITEMS,
    }


def redeem_shop_item(
    conn,
    student_id: int,
    item_code: str,
    request: Optional[Request] = None,
    response: Optional[Response] = None,
) -> dict:
    """Atomically redeem a shop item if `coin_balance >= cost_coins`."""
    _ensure_tables(conn)
    if request is not None:
        hydrate_student_wallet(request, conn, {"id": student_id, "role": "student"}, force_blob=True)

    item = SHOP_ITEMS_BY_CODE.get(str(item_code or "").strip())
    if not item:
        return {"success": False, "error": "Invalid shop item selected."}

    bal = recompute_coin_balance(conn, student_id)
    cost = int(item["cost_coins"])
    if bal < cost:
        needed = cost - bal
        return {
            "success": False,
            "error": f"You need {needed} more coins to redeem {item['title']} ({cost} Coins = Rs {item['inr_value']}).",
            "coin_balance": bal,
        }

    suffix = secrets.token_hex(3).upper()
    coupon = f"{item['prefix']}-{suffix}"
    conn.execute(
        """
        INSERT INTO coin_redemptions (student_id, item_code, item_title, coins_spent, inr_value, coupon_code)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (student_id, item["code"], item["title"], cost, int(item["inr_value"]), coupon),
    )
    conn.commit()
    new_bal = recompute_coin_balance(conn, student_id)
    persist_wallet(conn, student_id, response=response, request=request)
    return {
        "success": True,
        "coupon_code": coupon,
        "item_title": item["title"],
        "coins_spent": cost,
        "inr_value": int(item["inr_value"]),
        "coin_balance": new_bal,
        "balance_inr": coins_to_inr(new_bal),
    }


def get_past_question_attempts(conn, student_id: int, question_id: int, current_attempt_id: int = 0, request: Optional[Request] = None) -> list[dict]:
    """Fetch up to 3 chronological prior student answers on `question_id` across DB + signed wallet cookie."""
    history: list[dict] = []
    seen_texts: set[str] = set()

    # 1. Cookie memory (serverless-safe across cold instances)
    if request is not None:
        raw_cookie = request.cookies.get("saxaz_wallet")
        if raw_cookie:
            ck = security.decode_signed_json(raw_cookie, "w1")
            if isinstance(ck, dict) and int(ck.get("uid") or -1) == int(student_id):
                qmem = ck.get("qmem") or {}
                for item in (qmem.get(str(question_id)) or []):
                    if isinstance(item, dict) and item.get("a"):
                        norm = str(item["a"]).strip().lower()
                        if norm and norm not in seen_texts:
                            seen_texts.add(norm)
                            history.append({"answer": str(item["a"])[:220], "marks": float(item.get("m") or 0)})

    # 2. SQLite `answers` table across current and past attempts
    try:
        rows = conn.execute(
            """
            SELECT ans.answer_text, COALESCE(ans.marks_awarded, 0)
            FROM answers ans
            JOIN attempts att ON ans.attempt_id = att.id
            WHERE att.student_id = ? AND ans.question_id = ?
            ORDER BY ans.id DESC
            LIMIT 6
            """,
            (student_id, question_id),
        ).fetchall()
        for r in reversed(rows):
            txt = str(r[0] or "").strip()
            norm = txt.lower()
            if txt and norm not in seen_texts:
                seen_texts.add(norm)
                history.append({"answer": txt[:220], "marks": float(r[1] or 0)})
    except Exception:
        pass

    return history[-3:]


def record_question_attempt_in_wallet(
    conn,
    student_id: int,
    question_id: int,
    answer_text: str,
    marks_awarded: float,
    request: Optional[Request] = None,
    response: Optional[Response] = None,
) -> None:
    """Store compact recent question answer history inside signed `saxaz_wallet` cookie for serverless continuity."""
    if response is None:
        return
    qmem: dict = {}
    if request is not None:
        raw_cookie = request.cookies.get("saxaz_wallet")
        if raw_cookie:
            ck = security.decode_signed_json(raw_cookie, "w1")
            if isinstance(ck, dict) and int(ck.get("uid") or -1) == int(student_id) and isinstance(ck.get("qmem"), dict):
                qmem = dict(ck["qmem"])

    qkey = str(question_id)
    prev_list = list(qmem.get(qkey) or [])
    clean_ans = str(answer_text or "").strip()[:180]
    if clean_ans:
        prev_list.append({"a": clean_ans, "m": round(float(marks_awarded or 0), 1)})
    qmem[qkey] = prev_list[-3:]
    # Trim total questions tracked in cookie to 25 most recent so cookie stays tiny
    if len(qmem) > 25:
        keep_keys = list(qmem.keys())[-25:]
        qmem = {k: qmem[k] for k in keep_keys}
    persist_wallet(conn, student_id, response=response, request=request, qmem_override=qmem)
