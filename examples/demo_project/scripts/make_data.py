"""生成演示项目的模拟原始数据（固定随机种子，每次结果一致）。

用法（在仓库根目录）：uv run python examples/demo_project/scripts/make_data.py

产出：
- data/raw/orders.csv：订单明细，一行 = 一个订单号下的一个 SKU，2024-07 至 2026-06。
- data/raw/sku_catalog.xlsx：SKU 商品目录，一行 = 一个 SKU。

故意放进去的质量问题（供 1.1 盘点、1.2 清洗使用）：
完全重复行（集中在 2025-03 的一次重复导入）、金额缺失、数量为负（退货）、
商品名称尾部空格与全角字符、少量未来日期。
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SEED = 20260915
N_ORDERS = 120_000

CATEGORIES = {
    "办公通用物资": (["A4复印纸", "中性笔", "文件夹", "订书机", "打印硒鼓", "U盘"], (5, 300), {3: 1.4, 9: 1.5}),
    "MRO工业品": (["六角螺栓", "轴承", "劳保手套", "安全帽", "扳手套装", "润滑油"], (8, 800), {4: 1.2, 10: 1.3}),
    "电力物资": (["电力电缆", "绝缘子", "避雷器", "接地线", "熔断器", "电能表"], (50, 5000), {11: 1.6, 12: 1.8}),
}
BRANDS = ["正泰", "德力西", "得力", "晨光", "世达", "3M", "施耐德", "远东"]
UNITS = ["国网某市供电公司", "某发电公司", "某检修分公司", "某物资公司", "某信息通信公司", "某建设公司"]
CHANNELS = ["商城下单", "框架协议", "竞价采购"]
PROVINCES = ["江苏", "浙江", "山东", "河南", "湖北", "四川"]
START = datetime(2024, 7, 1)
MONTHS = 24


def make_skus(rng: random.Random) -> list[dict]:
    skus = []
    for cat, (names, (lo, hi), _) in CATEGORIES.items():
        for i in range(1000):
            name = rng.choice(names)
            spec = f"{rng.choice(['标准', '加厚', '工业级', '通用'])}{rng.randint(1, 99)}型"
            skus.append({
                "SKU": f"SKU{len(skus) + 1:05d}", "商品名称": f"{name} {spec}", "类目": cat,
                "品牌": rng.choice(BRANDS), "参考价": round(rng.uniform(lo, hi), 2),
                "上架时间": START - timedelta(days=rng.randint(0, 900)),
                "状态": rng.choices(["在售", "下架"], [0.9, 0.1])[0],
            })
    return skus


def month_weight(cat: str, month: int) -> float:
    return CATEGORIES[cat][2].get(month, 1.0)


def make_orders(rng: random.Random, skus: list[dict]) -> list[list]:
    by_cat = {c: [s for s in skus if s["类目"] == c] for c in CATEGORIES}
    rows = []
    for n in range(N_ORDERS):
        m = rng.randrange(MONTHS)
        day = START + timedelta(days=30.4 * m + rng.random() * 30)
        cat = rng.choices(list(CATEGORIES), [month_weight(c, day.month) * w for c, w in zip(CATEGORIES, (5, 3, 2))])[0]
        sku = rng.choice(by_cat[cat])
        qty = max(1, int(rng.lognormvariate(1.2, 0.9)))
        price = round(sku["参考价"] * rng.uniform(0.9, 1.1), 2)
        name = sku["商品名称"]
        if rng.random() < 0.03:
            name = name + " " if rng.random() < 0.5 else name.replace("A4", "Ａ４").replace("3M", "３Ｍ") + "　"
        amount: float | str = round(qty * price, 2)
        if rng.random() < 0.003:
            qty, amount = -qty, round(-qty * price, 2)
        if rng.random() < 0.005:
            amount = ""
        if n < 2:
            day = datetime(2027, 1, 5)
        rows.append([
            f"SO{day:%Y%m}{n:06d}", day.strftime("%Y-%m-%d %H:%M:%S"), rng.choice(UNITS), cat, sku["SKU"], name,
            sku["品牌"], qty, price, amount, rng.choice(CHANNELS), rng.choice(PROVINCES),
        ])
    dup = [r for r in rows if r[1].startswith("2025-03")]
    rows += rng.sample(dup, k=min(len(dup), 900)) + rng.sample(rows, 100)
    rows.sort(key=lambda r: r[1])
    return rows


def main() -> None:
    rng = random.Random(SEED)
    RAW.mkdir(parents=True, exist_ok=True)
    skus = make_skus(rng)
    rows = make_orders(rng, skus)
    with open(RAW / "orders.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["订单号", "下单时间", "采购单位", "类目", "SKU", "商品名称", "品牌", "数量", "单价", "金额", "渠道", "省份"])
        writer.writerows(rows)
    wb = Workbook()
    ws = wb.active
    ws.title = "SKU目录"
    ws.append(list(skus[0]))
    for s in skus:
        ws.append(list(s.values()))
    wb.save(RAW / "sku_catalog.xlsx")
    print(f"orders.csv：{len(rows):,} 行；sku_catalog.xlsx：{len(skus):,} 行 → {RAW}")


if __name__ == "__main__":
    main()
