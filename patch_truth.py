#!/usr/bin/env python3
"""Real $0.25 loss only, keep the live stop across a restart, report the real fill."""
import os
import shutil
import py_compile

TARGET = "main.py"
BACKUP = "main.py.bak_truth"

REPLACEMENTS = [
(
"""        if risk_usd > 0 and abs(realized) > 1e-8:
            raw = realized / risk_usd
            if raw > cap_hi or raw < cap_lo:
                logger.info(
                    f"📉 R clamp {symbol} | raw={raw:.2f} last={last:.2f} peak={peak:.2f} → use last"
                )
                return last
            return raw
""",
"""        if risk_usd > 0 and abs(realized) > 1e-8:
            raw = realized / risk_usd
            # Only hide a crazy profit print. A real loss must be shown as a loss.
            if raw > max(peak, last, 0.0) + 1.0:
                logger.info(
                    f"📉 R clamp {symbol} | raw={raw:.2f} last={last:.2f} peak={peak:.2f} → use last"
                )
                return last
            return raw
"""
),
(
"""            wide_dist = stop_dist * 1.05
            sl_dist = wide_dist
            cut_usd = float(getattr(config, "LOSS_CUT_USD", 0.25))
            if qty > 0 and cut_usd > 0:
                sl_dist = min(wide_dist, cut_usd / qty)
            emergency_sl_price = await adjust_price(
                entry_price - sl_dist if side == "BUY" else entry_price + sl_dist, symbol
            )
            logger.info(f"📏 Exchange SL {symbol} | ${cut_usd:.2f} cap | dist={sl_dist:.8g} wide={wide_dist:.8g}")

            async def _cap_already_crossed() -> bool:
                try:
                    last_px = float((await client.futures_ticker(symbol=symbol))["lastPrice"])
                except Exception:
                    return False
                if last_px <= 0:
                    return False
                stop_px = float(emergency_sl_price)
                if side == "BUY":
                    return last_px <= stop_px
                return last_px >= stop_px
""",
"""            wide_dist = stop_dist * 1.05
            sl_dist = wide_dist
            cut_usd = float(getattr(config, "LOSS_CUT_USD", 0.25))
            tick = 0.0
            try:
                tick = float((await get_symbol_precision(symbol)).get("tick_size") or 0)
            except Exception:
                tick = 0.0
            if qty > 0 and cut_usd > 0:
                dollar_dist = cut_usd / float(qty)
                if tick <= 0 or dollar_dist >= tick:
                    sl_dist = min(wide_dist, dollar_dist)
                else:
                    logger.info(
                        f"📏 $0.25 inside one tick {symbol} | dollar={dollar_dist:.8g} tick={tick:.8g} → wide stop"
                    )
            emergency_sl_price = await adjust_price(
                entry_price - sl_dist if side == "BUY" else entry_price + sl_dist, symbol
            )
            on_loss_side = (
                (side == "BUY" and float(emergency_sl_price) < float(entry_price))
                or (side == "SELL" and float(emergency_sl_price) > float(entry_price))
            )
            if not on_loss_side:
                sl_dist = wide_dist
                emergency_sl_price = await adjust_price(
                    entry_price - sl_dist if side == "BUY" else entry_price + sl_dist, symbol
                )
                logger.info(f"📏 rounded stop sat on entry {symbol} → wide stop @ {emergency_sl_price}")
            logger.info(f"📏 Exchange SL {symbol} | ${cut_usd:.2f} cap | dist={sl_dist:.8g} wide={wide_dist:.8g}")

            async def _cap_already_crossed() -> bool:
                # Close only when the exchange itself shows an open loss of $0.25.
                # A last-price touch is not enough: a rounded stop can sit on the entry.
                try:
                    rows = await client.futures_position_information(symbol=symbol)
                except Exception:
                    return False
                for row in rows or []:
                    if row.get("symbol") != symbol:
                        continue
                    if abs(float(row.get("positionAmt") or 0)) <= 0.0001:
                        continue
                    try:
                        upnl = float(row.get("unRealizedProfit") or 0)
                    except Exception:
                        return False
                    return upnl <= -float(cut_usd)
                return False
"""
),
(
"""                open_orders = await client.futures_get_open_orders(symbol=symbol)
                has_sl = any(
                    o.get('type') in ('STOP_MARKET', 'STOP', 'TRAILING_STOP_MARKET') 
                    or o.get('closePosition') in (True, 'true', 'True')
                    for o in open_orders
                )
                if not has_sl:
""",
"""                open_orders = await client.futures_get_open_orders(symbol=symbol)
                live_stop = 0.0
                for o in open_orders or []:
                    typ = str(o.get("type") or "").upper()
                    is_stop = (
                        typ in ("STOP_MARKET", "STOP", "STOP_LOSS", "STOP_LOSS_LIMIT", "TRAILING_STOP_MARKET")
                        or o.get("closePosition") in (True, "true", "True")
                    )
                    try:
                        sp = float(o.get("stopPrice") or 0)
                    except Exception:
                        sp = 0.0
                    if not is_stop or sp <= 0:
                        continue
                    if live_stop <= 0:
                        live_stop = sp
                    elif side == "BUY":
                        live_stop = max(live_stop, sp)
                    else:
                        live_stop = min(live_stop, sp)
                if live_stop > 0:
                    _best_stop_px[symbol] = live_stop
                    logger.info(f"📌 kept live stop {symbol} @ {live_stop}")
                has_sl = live_stop > 0
                if not has_sl:
"""
),
]


def main():
    if not os.path.exists(TARGET):
        print(f"STOPPED missing {TARGET}")
        return
    shutil.copy2(TARGET, BACKUP)
    text = open(TARGET, encoding="utf-8").read()
    for i, (old, new) in enumerate(REPLACEMENTS, 1):
        n = text.count(old)
        if n != 1:
            shutil.copy2(BACKUP, TARGET)
            print(f"STOPPED piece {i} count={n}")
            print(f"restored from {BACKUP} — bot file was not changed")
            return
        text = text.replace(old, new, 1)
    open(TARGET, "w", encoding="utf-8").write(text)
    try:
        py_compile.compile(TARGET, doraise=True)
    except Exception as e:
        shutil.copy2(BACKUP, TARGET)
        print(f"STOPPED compile: {e}")
        print(f"restored from {BACKUP} — bot file was not changed")
        return
    print(f"DONE pieces={len(REPLACEMENTS)}")
    print(f"backup={BACKUP}")


if __name__ == "__main__":
    main()
