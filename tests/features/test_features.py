from pytest_bdd import scenario
from pytest_bdd.feature import get_features

# We need to inject the session_type fixture to ensure proper setup
for feature in get_features(["USAGE.feature.md"]):
    # Dynamically create test functions for each scenario in the feature
    for scenario_obj in feature.scenarios.values():
        test_name = f"test_{scenario_obj.name.lower().replace(' ', '_')}"
        # The lambda function is a placeholder to inject the session_type fixture
        globals()[test_name] = scenario(feature.filename, scenario_obj.name)(
            lambda session_type: None  # pyright: ignore[reportUnknownArgumentType, reportUnknownLambdaType]
        )
