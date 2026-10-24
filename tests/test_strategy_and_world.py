import json
import unittest

import _paths
import jarvis_strategy_layer_v1 as strategy
import jarvis_world_core_v4_clienti as world


class StrategyLayerTest(unittest.TestCase):
    def test_mission_choice(self):
        self.assertEqual(strategy.choose_mission("vendere il libro"), "BOOK")
        self.assertEqual(strategy.choose_mission("find SME clients"), "SME_SUPPORT")
        self.assertEqual(strategy.choose_mission("anything else"), "MAKE_MONEY")

    def test_plan_without_model_lists_external_actions_as_gated(self):
        p = strategy.plan("libro", use_model=False)
        self.assertTrue(all(v == "APPROVAL_REQUIRED" for v in p["external_actions"].values()))

    def test_unknown_action_kind_is_treated_as_external(self):
        self.assertEqual(strategy.request_action("delete_website", {})["status"], "BLOCKED")

    def test_approval_bound_to_content(self):
        e = {"to": "a@example.org", "body": "x"}
        ok = strategy.approve("email", e, "owner")
        self.assertEqual(strategy.request_action("email", e, ok)["status"], "READY_TO_EXECUTE")
        self.assertEqual(strategy.request_action("email", dict(e, body="y"), ok)["reason"], "APPROVAL_DOES_NOT_MATCH_CONTENT")
        with self.assertRaises(ValueError):
            strategy.approve("email", e, "")


class WorldCoreTest(unittest.TestCase):
    def sample(self):
        return json.loads((_paths.ROOT / "examples" / "cities_sample.json").read_text(encoding="utf-8"))["cities"]

    def test_scores_sorted_and_bounded(self):
        rows = world.punteggia(self.sample())
        scores = [r["punteggio"] for r in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 <= s <= 100 for s in scores))
        self.assertEqual(rows[0]["citta"], "Milano")

    def test_missing_data_does_not_crash(self):
        rows = world.punteggia([{"citta": "A", "attivita": None, "notizie_crisi_90g": 3, "popolazione": 1000},
                                {"citta": "B", "attivita": 10, "notizie_crisi_90g": None, "popolazione": None}])
        self.assertEqual(len(rows), 2)

    def test_levels_and_antennas(self):
        self.assertEqual(world.antenne(80, 500000)[0], "HOT")
        self.assertIn("PUBBLICO_CONSUMER", world.antenne(80, 500000)[2])
        self.assertEqual(world.antenne(50, 1000)[0], "MEDIA")
        self.assertEqual(world.antenne(10, 1000), ("BASSA", "NON_SPENDERE_RISORSE", []))


if __name__ == "__main__":
    unittest.main()
