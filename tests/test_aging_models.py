from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from emulator import CONTROL_OPS, EPUEmulator
from epu import (
    AGING_MODELS,
    AGING_MODEL_SCHEMA_VERSION,
    EPU,
    EPUError,
    INSTRUCTION_STRESS,
    NATIVE_OPS,
)
from epu_spec import spec_payload


class AgingModelTests(unittest.TestCase):
    def test_models_publish_versioned_seed_free_coefficients(self) -> None:
        epu = EPU()

        default = epu.aging_model_info()
        epu.cr["aging_model"] = "aging"
        aging = epu.aging_model_info()

        self.assertEqual(AGING_MODEL_SCHEMA_VERSION, 1)
        self.assertEqual(default["model_id"], "simple-v0")
        self.assertEqual(default["model_version"], 0)
        self.assertEqual(aging["model_id"], "aging-v1")
        self.assertEqual(aging["model_version"], 1)
        self.assertTrue(aging["deterministic"])
        self.assertFalse(aging["requires_seed"])
        self.assertEqual(
            set(aging["coefficients"]),
            {
                "temperature_noise_rate",
                "stress_noise_rate",
                "temperature_health_rate",
                "stress_health_rate",
                "observation_noise_scale",
                "observation_health_loss",
                "refresh_noise_retention",
                "refresh_health_recovery",
                "refresh_health_ceiling",
            },
        )
        self.assertEqual(AGING_MODELS["aging-v1"].model_version, 1)
        self.assertEqual(
            aging["coefficients"],
            {
                "temperature_noise_rate": 0.0004,
                "stress_noise_rate": 0.0002,
                "temperature_health_rate": 0.00004,
                "stress_health_rate": 0.00002,
                "observation_noise_scale": 1.0,
                "observation_health_loss": 0.001,
                "refresh_noise_retention": 0.25,
                "refresh_health_recovery": 0.002,
                "refresh_health_ceiling": 0.995,
            },
        )
        published = spec_payload()["aging_models"]
        self.assertEqual(published["schema_version"], 1)
        self.assertEqual(published["default"], "simple-v0")
        self.assertEqual(published["aliases"]["aging"], "aging-v1")
        self.assertFalse(
            published["models"]["aging-v1"]["requires_seed"]
        )
        self.assertEqual(
            set(INSTRUCTION_STRESS),
            set(NATIVE_OPS) | set(CONTROL_OPS),
        )

    def test_simple_v0_preserves_static_metadata_for_normal_cycles(self) -> None:
        epu = EPU()
        epu.er["ER0"].temperature = 0.25

        for _ in range(5):
            epu.step("EMOV ER0, ER0")

        self.assertEqual(epu.er["ER0"].noise, 0.0)
        self.assertEqual(epu.er["ER0"].health, 1.0)
        self.assertTrue(
            all(event["aging_model"] == "simple-v0" for event in epu.timeline())
        )

    def test_aging_v1_is_deterministic_and_monotone(self) -> None:
        def run_once() -> tuple[list[float], list[float], list[dict[str, object]]]:
            epu = EPU()
            epu.cr["aging_model"] = "aging-v1"
            epu.step("ECONST ER0, 3")
            noises = [epu.er["ER0"].noise]
            health = [epu.er["ER0"].health]
            for _ in range(8):
                epu.step("EMUL ER0, ER0, ER0")
                noises.append(epu.er["ER0"].noise)
                health.append(epu.er["ER0"].health)
            return noises, health, epu.timeline()

        first = run_once()
        second = run_once()

        self.assertEqual(first, second)
        self.assertTrue(all(a <= b for a, b in zip(first[0], first[0][1:])))
        self.assertTrue(all(a >= b for a, b in zip(first[1], first[1][1:])))
        self.assertGreater(first[0][-1], first[0][0])
        self.assertLess(first[1][-1], first[1][0])

    def test_post_cooling_heat_and_instruction_stress_drive_aging(self) -> None:
        epu = EPU()
        epu.cr["aging_model"] = "aging-v1"
        epu.er["ER0"].temperature = 1.0
        epu.er["ER1"].temperature = 0.0

        epu.step("EMOV ER1, ER1")

        # ER0 is not an instruction target, so its change is temperature-only.
        self.assertAlmostEqual(epu.er["ER0"].temperature, 0.995)
        self.assertAlmostEqual(epu.er["ER0"].noise, 0.000000796)
        self.assertAlmostEqual(epu.er["ER0"].health, 0.9999602)
        # ER1 is cold after cooling but still ages from target-local work.
        self.assertEqual(epu.er["ER1"].temperature, 0.0)
        self.assertAlmostEqual(epu.er["ER1"].noise, 0.00000004)
        self.assertAlmostEqual(epu.er["ER1"].health, 0.999998)

    def test_cycle_order_is_semantic_heat_cooling_then_aging(self) -> None:
        epu = EPU()
        epu.cr["aging_model"] = "aging-v1"

        epu.step("ECONST ER0, 1")

        # ECONST contributes 0.02 heat, register cooling removes 0.005, then
        # aging observes T=0.015 plus ECONST stress=0.25.
        self.assertAlmostEqual(epu.er["ER0"].temperature, 0.015)
        self.assertAlmostEqual(epu.er["ER0"].noise, 0.000000112)
        self.assertAlmostEqual(epu.er["ER0"].health, 0.9999944)

    def test_observation_and_eprint_share_aging_transition(self) -> None:
        low = EPU()
        low.cr["aging_model"] = "aging-v1"
        low.step("ECONST ER0, 1")
        low.step("EOBS OUT0, ER0")

        high = EPU()
        high.cr["aging_model"] = "aging-v1"
        EPUEmulator(epu=high).run("ECONST ER0, 1\nEPRINT ER0")

        self.assertEqual(low.er["ER0"].noise, high.er["ER0"].noise)
        self.assertEqual(low.er["ER0"].health, high.er["ER0"].health)
        self.assertGreater(low.er["ER0"].noise, 0.0)
        self.assertLess(low.er["ER0"].health, 1.0)

    def test_refresh_reduces_noise_but_only_repairs_health_to_ceiling(self) -> None:
        epu = EPU()
        epu.cr["aging_model"] = "aging-v1"
        value = epu.er["ER0"]
        value.noise = 0.1
        value.health = 0.9
        value.temperature = 0.0

        epu.step("EREFRESH ER0")

        self.assertGreater(value.noise, 0.0)
        self.assertLess(value.noise, 0.1)
        self.assertGreater(value.health, 0.9)
        self.assertLessEqual(
            value.health,
            AGING_MODELS["aging-v1"].refresh_health_ceiling,
        )
        for _ in range(100):
            epu.step("EREFRESH ER0")
        self.assertEqual(
            value.health,
            AGING_MODELS["aging-v1"].refresh_health_ceiling,
        )

    def test_coupled_field_temperature_ages_neighbor_and_cells(self) -> None:
        epu = EPU()
        epu.run("EALLOC EP0, COLD, 1\nEALLOC EP1, COLD, 2")
        hot_pointer = epu.ep["EP0"]
        cold_pointer = epu.ep["EP1"]
        assert hot_pointer is not None and cold_pointer is not None
        hot = epu.fields[hot_pointer.field_id]
        cold = epu.fields[cold_pointer.field_id]
        epu.cr["thermal_model"] = "coupled-v1"
        epu.cr["aging_model"] = "aging-v1"
        epu.bank_meta["COLD"].base_temperature = 0.0
        epu.bank_meta["COLD"].cooling_rate = 0.0
        hot.temperature = 1.0
        cold.temperature = 0.0
        for field in (hot, cold):
            field.noise = 0.0
            field.health = 1.0
            for index in range(field.length):
                cell = epu.banks[field.bank_id][field.offset + index]
                cell.temperature = field.temperature
                cell.noise = 0.0
                cell.health = 1.0

        epu.step("EMOV ER15, ER15")

        self.assertGreater(cold.temperature, 0.0)
        self.assertGreater(cold.noise, 0.0)
        self.assertLess(cold.health, 1.0)
        cells = epu.banks[cold.bank_id][cold.offset : cold.offset + cold.length]
        self.assertTrue(all(cell.noise == cold.noise for cell in cells))
        self.assertTrue(all(cell.health == cold.health for cell in cells))

    def test_pointer_named_diagnostic_applies_field_instruction_stress(self) -> None:
        epu = EPU()
        epu.run("EALLOC EP0, COLD, 1")
        pointer = epu.ep["EP0"]
        assert pointer is not None
        field = epu.fields[pointer.field_id]
        epu.cr["aging_model"] = "aging-v1"
        epu.bank_meta["COLD"].base_temperature = 0.0
        epu.bank_meta["COLD"].cooling_rate = 0.0
        field.temperature = 0.0
        field.noise = 0.0
        field.health = 1.0

        epu.step("ETRACE EP0")

        self.assertGreater(field.noise, 0.0)
        self.assertLess(field.health, 1.0)

    def test_unknown_model_fails_closed_even_under_warn_policy(self) -> None:
        epu = EPU()
        epu.cr["aging_model"] = "future-random"
        epu.cr["exception_policy"] = "WARN"
        before = deepcopy(epu.er)

        with self.assertRaises(EPUError) as captured:
            epu.step("ECONST ER0, 9")

        self.assertEqual(captured.exception.code, "AGING_MODEL_ERROR")
        self.assertEqual(epu.er, before)
        self.assertEqual(epu.tick, 0)
        event = epu.timeline()[-1]
        self.assertEqual(event["exception"], "AGING_MODEL_ERROR")
        self.assertEqual(event["aging_model"], "future-random")


if __name__ == "__main__":
    unittest.main()
