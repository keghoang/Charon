import unittest

from charon.color_management import resolve_aces_decision


class ResolveAcesDecisionTests(unittest.TestCase):
    def test_ocio_with_rec709_working_space_is_not_aces(self):
        # nuke-default OCIO config: OCIO mode but scene-linear Rec.709-sRGB.
        self.assertIs(
            resolve_aces_decision(
                "OCIO",
                "scene_linear (scene-linear Rec.709-sRGB)",
                "nuke-default",
            ),
            False,
        )

    def test_ocio_with_acescg_working_space_is_aces(self):
        self.assertIs(
            resolve_aces_decision("OCIO", "ACES - ACEScg", ""),
            True,
        )

    def test_ocio_with_scene_linear_role_resolving_to_acescg(self):
        self.assertIs(
            resolve_aces_decision("OCIO", "scene_linear (ACEScg)", ""),
            True,
        )

    def test_aces_config_name_decides_when_working_space_ambiguous(self):
        self.assertIs(
            resolve_aces_decision("OCIO", "scene_linear", "aces_1.2"),
            True,
        )

    def test_ocio_env_path_with_aces_decides(self):
        self.assertIs(
            resolve_aces_decision(
                "OCIO",
                "",
                r"\\buck\pipeline\ocio\studio-config-aces-v1.3.ocio",
            ),
            True,
        )

    def test_nuke_default_config_decides_not_aces(self):
        self.assertIs(resolve_aces_decision("OCIO", "", "nuke-default"), False)

    def test_legacy_nuke_color_management_is_not_aces(self):
        self.assertIs(resolve_aces_decision("Nuke", "sRGB", ""), False)

    def test_unknown_setup_returns_none_for_preference_fallback(self):
        self.assertIsNone(resolve_aces_decision("OCIO", "scene_linear", ""))

    def test_missing_settings_return_none(self):
        self.assertIsNone(resolve_aces_decision("", "", ""))


if __name__ == "__main__":
    unittest.main()
