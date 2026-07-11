from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epu import EPU


program = """
ECONST ER0, 12.5
ECONST ER1, 4.25
EMUL ER2, ER0, ER1
ENORM ER2
ESHIFT ER3, ER2, 1
EOBS OUT_PRODUCT_E, ER3 ; precision=8

EALLOC EP0, COLD, 4 ; mode=EWORD
ESTORE EP0, ER3
ELOAD ER4, EP0
EQUANT ER5, ER4, 27
ETHERM OUT_THERMAL, ER5
ETRACE ER5
EREFRESH ER5
ESNAP SNAP0, ER5
"""


if __name__ == "__main__":
    epu = EPU()
    output = epu.run(program)

    for key, value in output.items():
        print(f"{key}: {value}")

    print("\nTIMELINE:")
    for event in epu.timeline():
        flags = ",".join(event["flags"])
        print(f"tick={event['tick']} op={event['op']} targets={event['targets']} flags={flags}")
