from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from epu import (
    EPU,
    EPUError,
    THERMAL_MODELS,
    THERMAL_MODEL_SCHEMA_VERSION,
)
from epu_spec import spec_payload


class ThermalModelTests(unittest.TestCase):
    def _allocate(self, epu: EPU, pointer: str, bank: str, length: int = 1) -> str:
        epu.step(f"EALLOC {pointer}, {bank}, {length}")
        resolved = epu.ep[pointer]
        assert resolved is not None
        return resolved.field_id

    def _isolate_from_ambient(self, epu: EPU) -> None:
        for meta in epu.bank_meta.values():
            meta.cooling_rate = 0.0
            meta.base_temperature = 0.0

    def _set_temperature(self, epu: EPU, field_id: str, value: float) -> None:
        field = epu.fields[field_id]
        field.temperature = value
        for index in range(field.length):
            epu.banks[field.bank_id][field.offset + index].temperature = value

    def test_models_publish_versioned_explicit_coefficients(self) -> None:
        epu = EPU()

        info = epu.thermal_model_info()

        self.assertEqual(THERMAL_MODEL_SCHEMA_VERSION, 1)
        self.assertEqual(info["configured_as"], "simple")
        self.assertEqual(info["model_id"], "simple-v0")
        self.assertEqual(info["model_version"], 0)
        self.assertEqual(
            set(info["coefficients"]),
            {
                "register_cooling_rate",
                "field_coupling",
                "bank_coupling",
                "ambient_cooling_scale",
                "cell_thermal_mass",
            },
        )
        self.assertEqual(THERMAL_MODELS["coupled-v1"].model_version, 1)
        published = spec_payload()["thermal_models"]
        self.assertEqual(published["schema_version"], 1)
        self.assertEqual(published["aliases"]["simple"], "simple-v0")
        self.assertEqual(
            published["models"]["coupled-v1"]["coefficients"]["bank_coupling"],
            0.025,
        )

    def test_default_simple_model_preserves_uncoupled_behavior(self) -> None:
        epu = EPU()
        hot = self._allocate(epu, "EP0", "COLD")
        cold = self._allocate(epu, "EP1", "COLD")
        self._isolate_from_ambient(epu)
        self._set_temperature(epu, hot, 1.0)
        self._set_temperature(epu, cold, 0.0)

        epu.step("EMOV ER15, ER15")

        self.assertEqual(epu.fields[hot].temperature, 1.0)
        self.assertEqual(epu.fields[cold].temperature, 0.0)

    def test_same_bank_exchange_is_mass_conserving_and_monotone(self) -> None:
        epu = EPU()
        epu.cr["thermal_model"] = "coupled-v1"
        hot = self._allocate(epu, "EP0", "COLD", 1)
        cold = self._allocate(epu, "EP1", "COLD", 3)
        self._isolate_from_ambient(epu)
        self._set_temperature(epu, hot, 1.0)
        self._set_temperature(epu, cold, 0.0)

        energy_before = sum(
            field.length * field.temperature for field in epu.fields.values()
        )
        gap_before = epu.fields[hot].temperature - epu.fields[cold].temperature
        epu.step("EMOV ER15, ER15")
        energy_after = sum(
            field.length * field.temperature for field in epu.fields.values()
        )
        gap_after = epu.fields[hot].temperature - epu.fields[cold].temperature

        self.assertAlmostEqual(epu.fields[hot].temperature, 0.90625)
        self.assertAlmostEqual(epu.fields[cold].temperature, 0.03125)
        self.assertAlmostEqual(energy_after, energy_before)
        self.assertGreater(gap_after, 0.0)
        self.assertLess(gap_after, gap_before)
        for field in epu.fields.values():
            cells = epu.banks[field.bank_id][field.offset : field.offset + field.length]
            self.assertTrue(all(cell.temperature == field.temperature for cell in cells))

    def test_bank_exchange_is_mass_conserving_and_does_not_overshoot(self) -> None:
        epu = EPU()
        epu.cr["thermal_model"] = "coupled-v1"
        hot = self._allocate(epu, "EP0", "COLD", 1)
        cold = self._allocate(epu, "EP1", "ARCHIVE", 3)
        self._isolate_from_ambient(epu)
        self._set_temperature(epu, hot, 1.0)
        self._set_temperature(epu, cold, 0.0)

        epu.step("EMOV ER15, ER15")

        self.assertAlmostEqual(epu.fields[hot].temperature, 0.98125)
        self.assertAlmostEqual(epu.fields[cold].temperature, 0.00625)
        self.assertAlmostEqual(
            epu.fields[hot].temperature + 3 * epu.fields[cold].temperature,
            1.0,
        )
        self.assertGreater(epu.fields[hot].temperature, epu.fields[cold].temperature)
        self.assertLess(epu.fields[hot].temperature, 1.0)
        self.assertGreater(epu.fields[cold].temperature, 0.0)

    def test_cycle_order_is_heat_then_exchange_then_ambient_cooling(self) -> None:
        epu = EPU()
        epu.cr["thermal_model"] = "coupled-v1"
        heated = self._allocate(epu, "EP0", "COLD")
        neighbor = self._allocate(epu, "EP1", "COLD")
        meta = epu.bank_meta["COLD"]
        meta.base_temperature = 0.0
        meta.cooling_rate = 0.001
        self._set_temperature(epu, heated, 0.0)
        self._set_temperature(epu, neighbor, 0.0)

        # ESTORE first sets EP0 from cold ER0, then contributes 0.02 instruction
        # heat.  Coupling moves 0.00125 to EP1 before both nodes cool by 0.001.
        epu.step("ESTORE EP0, ER0")

        self.assertAlmostEqual(epu.fields[heated].temperature, 0.01775)
        self.assertAlmostEqual(epu.fields[neighbor].temperature, 0.00025)

    def test_coupled_transition_is_deterministic(self) -> None:
        def run_once() -> tuple[list[float], list[list[float]]]:
            epu = EPU()
            epu.cr["thermal_model"] = "coupled"
            fields = [
                self._allocate(epu, "EP0", "COLD", 1),
                self._allocate(epu, "EP1", "COLD", 2),
                self._allocate(epu, "EP2", "ARCHIVE", 3),
            ]
            self._isolate_from_ambient(epu)
            for field_id, temperature in zip(fields, (1.0, 0.4, 0.0)):
                self._set_temperature(epu, field_id, temperature)
            for _ in range(12):
                epu.step("EMOV ER15, ER15")
            temperatures = [epu.fields[name].temperature for name in sorted(epu.fields)]
            cells = [
                [cell.temperature for cell in epu.banks[name]]
                for name in sorted(epu.banks)
            ]
            return temperatures, cells

        self.assertEqual(run_once(), run_once())

    def test_unknown_model_fails_closed_even_under_warn_policy(self) -> None:
        epu = EPU()
        epu.cr["thermal_model"] = "future-maybe"
        epu.cr["exception_policy"] = "WARN"
        before = deepcopy(epu.er)

        with self.assertRaises(EPUError) as captured:
            epu.step("ECONST ER0, 9")

        self.assertEqual(captured.exception.code, "THERMAL_MODEL_ERROR")
        self.assertEqual(epu.er, before)
        self.assertEqual(epu.tick, 0)
        self.assertEqual(epu.timeline()[-1]["exception"], "THERMAL_MODEL_ERROR")


if __name__ == "__main__":
    unittest.main()
