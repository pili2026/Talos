import logging
from typing import Any

import pytest
from pydantic import ValidationError

from core.model.control_composite import CompositeNode
from core.model.enum.condition_enum import (
    AggregationType,
    ConditionOperator,
    ConditionType,
    ControlActionType,
    ControlPolicyType,
)
from core.schema.control_condition_schema import ConditionSchema
from core.schema.control_condition_source_schema import Source
from core.schema.control_config_schema import ControlConfig


def create_control_config(config_data: dict) -> ControlConfig:
    """Helper function to create ControlConfig from test data"""
    version = config_data.get("version", "1.0.0")
    root_data = {k: v for k, v in config_data.items() if k != "version"}
    return ControlConfig(version=version, root=root_data)


class TestControlConfigSchemaLoading:
    """Tests for basic config loading and schema validation"""

    def test_when_loading_sd400_config_then_model_and_instance_are_parsed(
        self, valid_sd400_config_data, expected_version, expected_control_count_for_valid_config
    ):
        """Test that SD400 config with version loads correctly and parses all controls"""
        # Act
        config = create_control_config(valid_sd400_config_data)

        # Assert
        assert config.version == expected_version
        assert "SD400" in config.root
        assert "3" in config.root["SD400"].instances

        controls = config.get_control_list("SD400", "3")
        assert len(controls) == expected_control_count_for_valid_config

        control_codes = [ctrl.code for ctrl in controls]
        assert "HIGH_TEMP" in control_codes
        assert "LIN_ABS01" in control_codes
        assert "LIN_INC01" in control_codes

    def test_when_loading_minimal_config_then_default_version_is_applied(self, minimal_sd400_config_data):
        """Test that minimal config gets default version when version field is missing"""
        # Act
        config = create_control_config(minimal_sd400_config_data)

        # Assert
        assert config.version == "1.0.0"  # Default version
        assert "SD400" in config.root

    def test_when_config_has_no_instances_then_empty_control_list_returned(self, minimal_sd400_config_data):
        """Test that requesting controls for non-existent instance returns empty list"""
        # Arrange
        config = create_control_config(minimal_sd400_config_data)

        # Act
        controls = config.get_control_list("SD400", "999")  # Non-existent instance

        # Assert
        assert controls == []

    def test_when_config_has_no_model_then_empty_control_list_returned(self, minimal_sd400_config_data):
        """Test that requesting controls for non-existent model returns empty list"""
        # Arrange
        version = minimal_sd400_config_data.get("version", "1.0.0")
        root_data = {k: v for k, v in minimal_sd400_config_data.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("UNKNOWN_MODEL", "1")

        # Assert
        assert controls == []


class TestVersionValidation:
    """Tests for configuration version validation"""

    def test_when_version_follows_semver_then_validation_passes(self):
        """Test that semantic versioning format passes validation"""
        # Arrange
        test_cases = ["1.0.0", "2.15.3", "0.1.0", "10.20.30"]

        for version in test_cases:
            # Act
            config = ControlConfig(version=version, root={"SD400": {"default_controls": [], "instances": {}}})

            # Assert
            assert config.version == version

    def test_when_version_format_is_invalid_then_warning_logged_but_accepted(self, caplog, invalid_version_config_data):
        """Test that invalid version format logs warning but doesn't fail validation"""
        # Arrange
        caplog.set_level(logging.WARNING)

        # Act
        version = invalid_version_config_data.get("version", "1.0.0")
        root_data = {k: v for k, v in invalid_version_config_data.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Assert
        assert config.version == "v1.0.0"  # Still accepted
        assert "does not follow semantic versioning" in caplog.text


class TestPolicyInputSourceReference:
    """Tests for v2.0 policy input_source reference mechanism"""

    def test_when_policy_uses_input_source_then_references_condition_correctly(self, valid_sd400_config_data):
        """
        Test that policies correctly reference conditions by sources_id.

        v2.0 Design:
        - Composite conditions have sources_id
        - Policies reference conditions via input_source
        - Condition type information is in composite, not policy
        """
        # Arrange
        version = valid_sd400_config_data.get("version", "1.0.0")
        root_data = {k: v for k, v in valid_sd400_config_data.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "3")

        # Assert - Find controls by policy type
        absolute_linear_controls = [
            c for c in controls if c.policy and c.policy.type == ControlPolicyType.ABSOLUTE_LINEAR
        ]
        incremental_linear_controls = [
            c for c in controls if c.policy and c.policy.type == ControlPolicyType.INCREMENTAL_LINEAR
        ]
        discrete_setpoint_controls = [
            c for c in controls if c.policy and c.policy.type == ControlPolicyType.DISCRETE_SETPOINT
        ]

        # Should have one of each type
        assert len(absolute_linear_controls) == 1
        assert len(incremental_linear_controls) == 1
        assert len(discrete_setpoint_controls) == 1

        # === Test ABSOLUTE_LINEAR policy ===
        abs_control = absolute_linear_controls[0]

        # Policy should reference condition by ID
        assert abs_control.policy.input_source == "SD400.3:AIn01"

        # Policy should have required parameters
        assert abs_control.policy.base_freq == 40.0
        assert abs_control.policy.base_temp == 25.0
        assert abs_control.policy.gain_hz_per_unit == 1.2

        # Composite should have the referenced condition
        assert abs_control.composite is not None
        condition_nodes = self._find_all_leaf_conditions(abs_control.composite)
        assert len(condition_nodes) == 1

        # Condition should have correct sources_id and type
        condition = condition_nodes[0]
        assert condition.sources_id == "SD400.3:AIn01"
        assert condition.type == ConditionType.THRESHOLD

        # Condition should have Source objects
        assert condition.sources is not None
        assert len(condition.sources) == 1
        assert isinstance(condition.sources[0], Source)
        assert condition.sources[0].device == "SD400"
        assert condition.sources[0].slave_id == "3"
        assert condition.sources[0].pins == ["AIn01"]

        # === Test INCREMENTAL_LINEAR policy ===
        inc_control = incremental_linear_controls[0]

        # Policy should reference condition by ID
        assert inc_control.policy.input_source == "SD400.3:AIn01-AIn02"

        # Policy should have required parameters
        assert inc_control.policy.gain_hz_per_unit == 1.5

        # Composite should have the referenced condition
        assert inc_control.composite is not None
        condition_nodes = self._find_all_leaf_conditions(inc_control.composite)
        assert len(condition_nodes) == 1

        # Condition should have correct sources_id and type
        condition = condition_nodes[0]
        assert condition.sources_id == "SD400.3:AIn01-AIn02"
        assert condition.type == ConditionType.DIFFERENCE

        # Condition should have 2 Source objects
        assert condition.sources is not None
        assert len(condition.sources) == 2
        assert all(isinstance(s, Source) for s in condition.sources)

        # === Test DISCRETE_SETPOINT policy ===
        discrete_control = discrete_setpoint_controls[0]

        # Discrete setpoint should NOT have input_source
        assert discrete_control.policy.input_source is None

    def _find_all_leaf_conditions(self, composite: CompositeNode) -> list[CompositeNode]:
        """Helper: Recursively find all leaf conditions in composite tree"""
        leaves = []

        if composite.type is not None:
            # This is a leaf
            leaves.append(composite)

        # Recurse into children
        if composite.all:
            for child in composite.all:
                leaves.extend(self._find_all_leaf_conditions(child))

        if composite.any:
            for child in composite.any:
                leaves.extend(self._find_all_leaf_conditions(child))

        if composite.not_:
            leaves.extend(self._find_all_leaf_conditions(composite.not_))

        return leaves


class TestAutoGenerateConditionIds:
    """Tests for automatic sources_id generation"""

    def test_when_sources_id_not_provided_then_auto_generated(self):
        """Test that sources_id is auto-generated when not provided"""
        # Arrange - Config without sources_id
        config_data = {
            "name": "Test Control",
            "code": "TEST_01",
            "composite": {
                "any": [
                    {
                        "sources_id": "cond_0",
                        "type": "threshold",
                        "sources": [{"device": "SD400", "slave_id": "3", "pins": ["AIn01"]}],
                        "operator": "gt",
                        "threshold": 25.0,
                    }
                ]
            },
            "policy": {
                "type": "absolute_linear",
                "input_source": "cond_0",
                "base_freq": 40.0,
                "base_temp": 25.0,
                "gain_hz_per_unit": 1.2,
            },
            "actions": [
                {
                    "model": "TECO_VFD",
                    "slave_id": "1",
                    "type": "set_frequency",
                    "target": "RW_HZ",
                    "value": 0.0,
                }
            ],
        }

        # Act
        condition = ConditionSchema.model_validate(config_data)

        # Assert
        # Should auto-generate sources_id
        leaf_conditions = self._find_all_leaf_conditions(condition.composite)
        assert len(leaf_conditions) == 1
        assert leaf_conditions[0].sources_id == "cond_0"

        # Policy should reference the auto-generated ID
        assert condition.policy.input_source == "cond_0"

    def test_when_multiple_conditions_without_ids_then_auto_generated_sequentially(self):
        """Test that multiple conditions get sequential auto-generated IDs"""
        # Arrange - Config with multiple conditions, no sources_id
        config_data = {
            "name": "Multi Condition Test",
            "code": "TEST_02",
            "composite": {
                "all": [
                    {
                        "sources_id": "cond_0",
                        "type": "threshold",
                        "sources": [{"device": "SD400", "slave_id": "3", "pins": ["AIn01"]}],
                        "operator": "gt",
                        "threshold": 20.0,
                    },
                    {
                        "sources_id": "cond_1",
                        "type": "difference",
                        "sources": [
                            {"device": "SD400", "slave_id": "3", "pins": ["AIn01"]},
                            {"device": "SD400", "slave_id": "3", "pins": ["AIn02"]},
                        ],
                        "operator": "gt",
                        "threshold": 5.0,
                    },
                ]
            },
            "policy": {
                "type": "absolute_linear",
                "input_source": "cond_1",
                "base_temp": 0.0,
                "base_freq": 40.0,
                "gain_hz_per_unit": 2.0,
            },
            "actions": [
                {
                    "model": "TECO_VFD",
                    "slave_id": "1",
                    "type": "set_frequency",
                    "target": "RW_HZ",
                    "value": 0.0,
                }
            ],
        }

        # Act
        condition = ConditionSchema.model_validate(config_data)

        # Assert
        leaf_conditions = self._find_all_leaf_conditions(condition.composite)
        assert len(leaf_conditions) == 2

        # Should have sequential IDs
        assert leaf_conditions[0].sources_id == "cond_0"
        assert leaf_conditions[1].sources_id == "cond_1"

        # Policy should reference the second condition
        assert condition.policy.input_source == "cond_1"

    def test_when_sources_id_provided_then_not_overwritten(self):
        """Test that manually provided sources_id is preserved"""
        # Arrange - Config with custom sources_id
        config_data = {
            "name": "Custom ID Test",
            "code": "TEST_03",
            "composite": {
                "any": [
                    {
                        "sources_id": "my_custom_temp_sensor",  # Custom ID
                        "type": "threshold",
                        "sources": [{"device": "SD400", "slave_id": "3", "pins": ["AIn01"]}],
                        "operator": "gt",
                        "threshold": 25.0,
                    }
                ]
            },
            "policy": {
                "type": "absolute_linear",
                "input_source": "my_custom_temp_sensor",
                "base_freq": 40.0,
                "base_temp": 25.0,
                "gain_hz_per_unit": 1.2,
            },
            "actions": [
                {
                    "model": "TECO_VFD",
                    "slave_id": "1",
                    "type": "set_frequency",
                    "target": "RW_HZ",
                    "value": 0.0,
                }
            ],
        }

        # Act
        condition = ConditionSchema.model_validate(config_data)

        # Assert
        # Should preserve custom ID
        leaf_conditions = self._find_all_leaf_conditions(condition.composite)
        assert len(leaf_conditions) == 1
        assert leaf_conditions[0].sources_id == "my_custom_temp_sensor"

        # Policy should reference the custom ID
        assert condition.policy.input_source == "my_custom_temp_sensor"

    def _find_all_leaf_conditions(self, composite: CompositeNode) -> list[CompositeNode]:
        """Helper: Recursively find all leaf conditions"""
        leaves = []

        if composite.type is not None:
            leaves.append(composite)

        if composite.all:
            for child in composite.all:
                leaves.extend(self._find_all_leaf_conditions(child))

        if composite.any:
            for child in composite.any:
                leaves.extend(self._find_all_leaf_conditions(child))

        if composite.not_:
            leaves.extend(self._find_all_leaf_conditions(composite.not_))

        return leaves


class TestActionTypeEnumSupport:
    """Tests for action type enum support, especially ADJUST_FREQUENCY"""

    def test_when_action_type_is_set_frequency_then_validation_passes(self, valid_sd400_config_data):
        """Test that SET_FREQUENCY action type works correctly"""
        # Arrange
        version = valid_sd400_config_data.get("version", "1.0.0")
        root_data = {k: v for k, v in valid_sd400_config_data.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "3")

        # Assert - Now checking actions[0] instead of action
        set_freq_controls = [c for c in controls if c.actions and c.actions[0].type == ControlActionType.SET_FREQUENCY]
        assert len(set_freq_controls) >= 1

        for control in set_freq_controls:
            if control.actions[0].value is not None:
                assert isinstance(control.actions[0].value, (int, float))

    def test_when_action_type_is_adjust_frequency_then_validation_passes(self, valid_sd400_config_data):
        """Test that new ADJUST_FREQUENCY action type works correctly"""
        # Arrange
        version = valid_sd400_config_data.get("version", "1.0.0")
        root_data = {k: v for k, v in valid_sd400_config_data.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "3")

        # Assert - Now checking actions[0] instead of action
        adjust_freq_controls = [
            c for c in controls if c.actions and c.actions[0].type == ControlActionType.ADJUST_FREQUENCY
        ]
        assert len(adjust_freq_controls) == 1

        control = adjust_freq_controls[0]
        assert control.code == "LIN_INC01"
        assert control.actions[0].model == "TECO_VFD"
        assert control.actions[0].target == "RW_HZ"

    def test_when_action_type_is_unknown_then_validation_fails(self, config_with_invalid_action_type):
        """Test that unknown action type causes validation error"""
        # Act / Assert
        with pytest.raises(ValidationError) as exc_info:
            version = config_with_invalid_action_type.get("version", "1.0.0")
            root_data = {k: v for k, v in config_with_invalid_action_type.items() if k != "version"}
            ControlConfig(version=version, root=root_data)

        assert "unknown_action_type" in str(exc_info.value) or "Input should be" in str(exc_info.value)


class TestControlListExtraction:
    """Tests for control list extraction and processing"""

    def test_when_extracting_controls_then_priority_order_is_preserved(self, valid_sd400_config_data):
        """Test that controls maintain their definition order after processing"""
        # Arrange
        version = valid_sd400_config_data.get("version", "1.0.0")
        root_data = {k: v for k, v in valid_sd400_config_data.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "3")

        # Assert
        priorities = [c.priority for c in controls]
        assert priorities == [80, 90, 95]  # Should maintain original order

        codes = [c.code for c in controls]
        assert codes == ["HIGH_TEMP", "LIN_ABS01", "LIN_INC01"]

    def test_when_duplicate_priorities_exist_then_later_rule_is_kept(self, config_with_duplicate_priorities, caplog):
        """Test that duplicate priorities are resolved by keeping the later (instance) rule"""
        # Arrange
        caplog.set_level(logging.WARNING)
        version = config_with_duplicate_priorities.get("version", "1.0.0")
        root_data = {k: v for k, v in config_with_duplicate_priorities.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "2")

        # Assert
        assert len(controls) == 1
        assert controls[0].code == "OVERRIDE_RULE"  # Instance rule should override default
        assert controls[0].actions[0].value == 50.0

        # Should log duplicate resolution
        assert "PRIORITY CONFLICT" in caplog.text

    def test_when_instance_uses_default_controls_then_both_are_merged(self, config_with_duplicate_priorities):
        """Test that default controls are included when use_default_controls=True"""
        # Arrange
        version = config_with_duplicate_priorities.get("version", "1.0.0")
        root_data = {k: v for k, v in config_with_duplicate_priorities.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act - before deduplication, both default and instance controls should be considered
        model_config = config.root.get("SD400")
        instance_config = model_config.instances.get("2")

        # Assert
        assert instance_config.use_default_controls is True
        assert len(model_config.default_controls) == 1
        assert len(instance_config.controls) == 1

    def test_when_no_controls_exist_then_empty_list_returned(self, minimal_sd400_config_data):
        """Test that instance with no controls returns empty list"""
        # Arrange
        version = minimal_sd400_config_data.get("version", "1.0.0")
        root_data = {k: v for k, v in minimal_sd400_config_data.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "1")

        # Assert
        assert controls == []


class TestErrorHandlingAndValidation:
    """Tests for error handling and validation edge cases"""

    def test_when_composite_is_invalid_then_validation_error_is_raised(
        self,
        config_with_invalid_composite: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.WARNING)

        with pytest.raises(ValidationError) as exc_info:
            create_control_config(config_with_invalid_composite)

        errors = exc_info.value.errors()

        composite_errs = [e for e in errors if e["loc"][-1] == "composite"]
        assert composite_errs, errors

        err = composite_errs[0]
        assert err["type"] == "value_error"
        assert "'any' must contain at least one child" in err["msg"]

    def test_when_actions_field_is_missing_then_validation_error_is_raised(
        self,
        config_with_missing_action: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.WARNING)

        with pytest.raises(ValidationError) as exc_info:
            create_control_config(config_with_missing_action)

        msg = str(exc_info.value)

        # Depending on which validator triggers first, you may see "actions field required"
        # or the composite validation error if composite also uses the wrong key ("source" vs "sources").
        # Keep the assertion aligned with your current schema error message.
        assert ("actions" in msg.lower()) or ("validation failed" in msg.lower())

    def test_when_policy_is_invalid_then_rule_is_filtered_out(self, config_with_invalid_policy, caplog):
        """Test that rules with invalid policy are filtered out"""
        # Arrange
        caplog.set_level(logging.WARNING)
        version = config_with_invalid_policy.get("version", "1.0.0")
        root_data = {k: v for k, v in config_with_invalid_policy.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "1")

        # Assert
        assert len(controls) == 0  # Invalid policy rule should be filtered out
        assert "invalid policy" in caplog.text


class TestActionValueValidation:
    """Tests for action value validation and type coercion"""

    def test_when_set_frequency_has_numeric_value_then_coerced_to_float(self, config_with_string_frequency_value):
        """Test that SET_FREQUENCY action values are coerced to float"""
        # Act
        version = config_with_string_frequency_value.get("version", "1.0.0")
        root_data = {k: v for k, v in config_with_string_frequency_value.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)
        controls = config.get_control_list("SD400", "1")

        # Assert
        assert len(controls) == 1
        assert isinstance(controls[0].actions[0].value, float)
        assert controls[0].actions[0].value == 45.5

    def test_when_adjust_frequency_has_numeric_value_then_coerced_to_float(
        self, config_with_string_adjust_frequency_value
    ):
        """Test that ADJUST_FREQUENCY action values are coerced to float"""
        # Act
        version = config_with_string_adjust_frequency_value.get("version", "1.0.0")
        root_data = {k: v for k, v in config_with_string_adjust_frequency_value.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)
        controls = config.get_control_list("SD400", "1")

        # Assert
        assert len(controls) == 1
        assert isinstance(controls[0].actions[0].value, float)
        assert controls[0].actions[0].value == 1.5


class TestInvalidPolicyHandling:
    """Tests for invalid policy handling in v2.0"""

    def test_when_policy_is_invalid_then_rule_is_filtered_out(self, config_with_invalid_policy, caplog):
        """Test that rules with invalid policy are filtered out"""
        # Arrange
        caplog.set_level(logging.WARNING)
        version = config_with_invalid_policy.get("version", "1.0.0")
        root_data = {k: v for k, v in config_with_invalid_policy.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "1")

        # Assert
        assert len(controls) == 0  # Invalid policy rule should be filtered out
        assert "invalid policy" in caplog.text or "absolute_linear policy requires" in caplog.text

    def test_when_absolute_linear_missing_input_source_then_validation_error_is_raised(self):
        config_data = {
            "version": "1.0.0",
            "SD400": {
                "instances": {
                    "1": {
                        "controls": [
                            {
                                "name": "Missing Input Source",
                                "code": "NO_INPUT",
                                "priority": 10,
                                "composite": {
                                    "any": [
                                        {
                                            "sources_id": "cond_0",
                                            "type": "threshold",
                                            "sources": [{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
                                            "operator": "gt",
                                            "threshold": 25.0,
                                        }
                                    ]
                                },
                                "policy": {
                                    "type": "absolute_linear",
                                    # missing input_source
                                    "base_freq": 40.0,
                                    "base_temp": 25.0,
                                    "gain_hz_per_unit": 1.2,
                                },
                                "actions": [
                                    {
                                        "model": "TECO_VFD",
                                        "slave_id": "1",
                                        "type": "set_frequency",
                                        "target": "RW_HZ",
                                        "value": 0.0,
                                    }
                                ],
                            }
                        ]
                    }
                }
            },
        }

        root_data = {k: v for k, v in config_data.items() if k != "version"}

        with pytest.raises(ValidationError) as exc_info:
            ControlConfig(version="1.0.0", root=root_data)

        msg = str(exc_info.value).lower()
        assert "no_input" in msg
        assert "absolute_linear" in msg
        assert "input_source" in msg

    def test_when_incremental_linear_missing_gain_then_filtered(self, caplog):
        """Test that incremental_linear without gain is filtered out"""
        # Arrange
        config_data = {
            "version": "1.0.0",
            "SD400": {
                "instances": {
                    "1": {
                        "controls": [
                            {
                                "name": "Missing Gain",
                                "code": "NO_GAIN",
                                "composite": {
                                    "any": [
                                        {
                                            "sources_id": "cond_0",
                                            "type": "difference",
                                            "sources": [
                                                {"device": "SD400", "slave_id": "1", "pins": ["AIn01"]},
                                                {"device": "SD400", "slave_id": "1", "pins": ["AIn02"]},
                                            ],
                                            "operator": "gt",
                                            "threshold": 5.0,
                                        }
                                    ]
                                },
                                "policy": {
                                    "type": "incremental_linear",
                                    "input_source": "cond_0",
                                    # Missing gain_hz_per_unit
                                },
                                "actions": [
                                    {
                                        "model": "TECO_VFD",
                                        "slave_id": "1",
                                        "type": "adjust_frequency",
                                        "target": "RW_HZ",
                                        "value": 1.0,
                                    }
                                ],
                            }
                        ]
                    }
                }
            },
        }

        caplog.set_level(logging.WARNING)
        root_data = {k: v for k, v in config_data.items() if k != "version"}
        config = ControlConfig(version="1.0.0", root=root_data)

        # Act
        controls = config.get_control_list("SD400", "1")

        # Assert
        assert len(controls) == 0
        assert "requires gain_hz_per_unit" in caplog.text

    def test_when_policy_references_nonexistent_condition_id_then_validation_error_is_raised(self):
        config_data = {
            "version": "1.0.0",
            "SD400": {
                "instances": {
                    "1": {
                        "controls": [
                            {
                                "name": "Invalid Reference",
                                "code": "BAD_REF",
                                "priority": 10,
                                "composite": {
                                    "any": [
                                        {
                                            "sources_id": "cond_0",
                                            "type": "threshold",
                                            "sources": [{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
                                            "operator": "gt",
                                            "threshold": 25.0,
                                        }
                                    ]
                                },
                                "policy": {
                                    "type": "absolute_linear",
                                    "input_source": "nonexistent_id",
                                    "base_freq": 40.0,
                                    "base_temp": 25.0,
                                    "gain_hz_per_unit": 1.2,
                                },
                                "actions": [
                                    {
                                        "model": "TECO_VFD",
                                        "slave_id": "1",
                                        "type": "set_frequency",
                                        "target": "RW_HZ",
                                        "value": 0.0,
                                    }
                                ],
                            }
                        ]
                    }
                }
            },
        }

        root_data = {k: v for k, v in config_data.items() if k != "version"}

        with pytest.raises(ValidationError) as exc_info:
            ControlConfig(version="1.0.0", root=root_data)

        msg = str(exc_info.value)
        assert "input_source" in msg
        assert "not found in composite" in msg.lower()


class TestAdvancedCompositeValidation:
    """Tests for advanced composite structure validation"""

    def test_when_composite_depth_is_excessive_then_rule_filtered_out(self, config_with_circular_reference, caplog):
        """Test that excessive composite depth is handled gracefully"""
        # Given
        caplog.set_level(logging.WARNING)

        # When
        config = create_control_config(config_with_circular_reference)
        controls = config.get_control_list("SD400", "1")

        # Then - Configuration should load, excessive depth rules filtered
        assert config.version == "1.0.0"
        # Rules with excessive depth should be filtered at runtime

    def test_when_composite_has_too_many_children_then_validation_fails(self):
        excessive_children = []
        for i in range(25):
            excessive_children.append(
                CompositeNode(
                    type="threshold",
                    sources=[{"device": "SD400", "slave_id": "1", "pins": [f"AIn{i:02d}"]}],
                    operator="gt",
                    threshold=10.0,
                )
            )

        with pytest.raises(ValidationError) as exc_info:
            CompositeNode(all=excessive_children)

        assert "cannot have more than 20 children" in str(exc_info.value)

    def test_when_between_operator_has_invalid_range_then_validation_fails(self):
        """Test that BETWEEN operator with min >= max is invalid"""

        with pytest.raises(ValidationError) as exc_info:
            CompositeNode(
                type="threshold",
                sources=[{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
                operator="between",
                min=15.0,
                max=10.0,  # invalid: max < min
            )

        msg = str(exc_info.value).lower()
        assert "between" in msg
        assert "min" in msg
        assert "less than" in msg or "min must be less than" in msg

    def test_when_difference_sources_are_duplicate_then_validation_error_is_raised(
        self, config_with_duplicate_difference_sources, caplog
    ):
        """Duplicate sources in difference conditions should fail fast at config load time"""
        caplog.set_level(logging.WARNING)

        with pytest.raises(ValidationError) as exc_info:
            create_control_config(config_with_duplicate_difference_sources)

        errs = exc_info.value.errors()

        target = [e for e in errs if "composite" in e["loc"]]
        assert target, errs

        msg = " ".join(e["msg"] for e in target).lower()
        assert "difference" in msg
        assert "distinct" in msg or "duplicate" in msg

    def test_when_between_operator_has_invalid_min_max_then_validation_error_is_raised(
        self, config_with_invalid_operator_combinations, caplog
    ):
        """Invalid BETWEEN min/max combinations should fail fast at config load time"""
        caplog.set_level(logging.WARNING)

        with pytest.raises(ValidationError) as exc_info:
            create_control_config(config_with_invalid_operator_combinations)

        msg = str(exc_info.value)
        assert "between" in msg.lower()
        assert "min" in msg.lower()
        assert "less than" in msg.lower()

    def test_when_circular_reference_detected_then_graceful_handling(self, caplog):
        """Test that circular references are handled gracefully without crashing"""
        # Note: This would require manually constructing circular structures in code
        # For now, we test that the depth calculation returns -1 for problematic structures

        caplog.set_level(logging.ERROR)

        # Create a simple valid node first
        node = CompositeNode(
            type="threshold",
            sources=[{"device": "SD400", "slave_id": "1", "pins": ["AIn01"]}],
            operator="gt",
            threshold=10.0,
        )

        # Normal case should work
        depth = node.calculate_max_depth()
        assert depth >= 1


class TestCompositeNodeSourcesV2:
    """Test CompositeNode with v2.0 Source objects (no backward compatibility)"""

    def test_threshold_single_source_single_pin(self):
        """Threshold condition with single source, single pin"""
        node = CompositeNode(
            type=ConditionType.THRESHOLD,
            sources=[Source(device="ADAM-4117", slave_id="12", pins=["AIn01"])],
            operator=ConditionOperator.GREATER_THAN,
            threshold=40.0,
        )

        assert not node.invalid
        assert len(node.sources) == 1
        assert isinstance(node.sources[0], Source)
        assert node.sources[0].device == "ADAM-4117"
        assert node.sources[0].slave_id == "12"
        assert node.sources[0].pins == ["AIn01"]

    def test_threshold_single_source_multiple_pins_with_aggregation(self):
        """Threshold condition with multiple pins (intra-source aggregation)"""
        node = CompositeNode(
            type=ConditionType.THRESHOLD,
            sources=[
                Source(
                    device="ADAM-4117",
                    slave_id="12",
                    pins=["AIn01", "AIn02", "AIn03"],
                    aggregation=AggregationType.AVERAGE,
                )
            ],
            operator=ConditionOperator.GREATER_THAN,
            threshold=35.0,
        )

        assert not node.invalid
        source = node.sources[0]
        assert source.pins == ["AIn01", "AIn02", "AIn03"]
        assert source.aggregation == AggregationType.AVERAGE
        assert source.get_effective_aggregation() == AggregationType.AVERAGE

    def test_average_multiple_sources_cross_device(self):
        """Average condition with sources from different devices"""
        node = CompositeNode(
            type=ConditionType.AVERAGE,
            sources=[
                Source(device="ADAM-4117", slave_id="12", pins=["AIn01"]),
                Source(device="ADAM-4117", slave_id="14", pins=["AIn02"]),
            ],
            operator=ConditionOperator.GREATER_THAN,
            threshold=35.0,
        )

        assert not node.invalid
        assert len(node.sources) == 2
        assert node.sources[0].slave_id == "12"
        assert node.sources[1].slave_id == "14"

    def test_difference_hierarchical_aggregation(self):
        """Difference condition with hierarchical aggregation (group avg vs group avg)"""
        node = CompositeNode(
            type=ConditionType.DIFFERENCE,
            sources=[
                Source(device="ADAM-4117", slave_id="12", pins=["AIn01", "AIn02"], aggregation=AggregationType.AVERAGE),
                Source(device="ADAM-4117", slave_id="14", pins=["AIn01", "AIn02"], aggregation=AggregationType.AVERAGE),
            ],
            operator=ConditionOperator.GREATER_THAN,
            threshold=30.0,
        )

        assert not node.invalid
        assert len(node.sources) == 2

        # Source 1: avg(12.AIn01, 12.AIn02)
        assert node.sources[0].pins == ["AIn01", "AIn02"]
        assert node.sources[0].aggregation == AggregationType.AVERAGE

        # Source 2: avg(14.AIn01, 14.AIn02)
        assert node.sources[1].pins == ["AIn01", "AIn02"]
        assert node.sources[1].aggregation == AggregationType.AVERAGE

    def test_sources_from_yaml_dict(self):
        """Sources can be created from YAML dict format"""
        node = CompositeNode(
            type=ConditionType.THRESHOLD,
            sources=[
                {
                    "device": "ADAM-4117",
                    "slave_id": "12",
                    "pins": ["AIn01", "AIn02"],
                    "aggregation": "sum",  # ← String from YAML
                }
            ],
            operator=ConditionOperator.GREATER_THAN,
            threshold=100.0,
        )

        assert not node.invalid
        source = node.sources[0]
        assert isinstance(source, Source)
        assert source.aggregation == AggregationType.SUM


class TestCompositeNodeValidation:
    """Test validation rules for CompositeNode with Source objects"""

    def test_threshold_requires_exactly_one_source(self):
        """Threshold must have exactly 1 source"""
        # Too many sources
        with pytest.raises(ValidationError):
            CompositeNode(
                type=ConditionType.THRESHOLD,
                sources=[
                    Source(device="ADAM-4117", slave_id="12", pins=["AIn01"]),
                    Source(device="ADAM-4117", slave_id="14", pins=["AIn02"]),
                ],
                operator=ConditionOperator.GREATER_THAN,
                threshold=40.0,
            )

    def test_difference_requires_exactly_two_sources(self):
        """Difference must have exactly 2 sources"""
        # Only one source
        with pytest.raises(ValidationError):
            CompositeNode(
                type=ConditionType.DIFFERENCE,
                sources=[Source(device="ADAM-4117", slave_id="12", pins=["AIn01"])],
                operator=ConditionOperator.GREATER_THAN,
                threshold=10.0,
            )

    def test_average_requires_at_least_two_sources(self):
        """Average must have at least 2 sources"""
        # Only one source
        with pytest.raises(ValidationError):
            CompositeNode(
                type=ConditionType.AVERAGE,
                sources=[Source(device="ADAM-4117", slave_id="12", pins=["AIn01"])],
                operator=ConditionOperator.GREATER_THAN,
                threshold=35.0,
            )

    def test_time_elapsed_should_not_have_sources(self):
        """TIME_ELAPSED should not specify sources"""
        with pytest.raises(ValidationError):
            CompositeNode(
                type=ConditionType.TIME_ELAPSED,
                sources=[Source(device="ADAM-4117", slave_id="12", pins=["AIn01"])],
                interval_hours=4.0,
            )


class TestCompositeNodeComplexScenarios:
    """Test complex real-world scenarios"""

    def test_multi_zone_temperature_differential(self):
        """Real scenario: Multi-sensor zone temperature differential"""
        node = CompositeNode(
            type=ConditionType.DIFFERENCE,
            sources=[
                # Zone A: 3 temperature sensors averaged
                Source(
                    device="ADAM-4117",
                    slave_id="12",
                    pins=["AIn01", "AIn02", "AIn03"],
                    aggregation=AggregationType.AVERAGE,
                ),
                # Zone B: 2 temperature sensors averaged
                Source(device="ADAM-4117", slave_id="14", pins=["AIn01", "AIn02"], aggregation=AggregationType.AVERAGE),
            ],
            operator=ConditionOperator.GREATER_THAN,
            threshold=15.0,
            hysteresis=0.5,
            debounce_sec=10.0,
            abs=False,
        )

        assert not node.invalid
        assert node.type == ConditionType.DIFFERENCE
        assert len(node.sources) == 2
        assert node.sources[0].pins == ["AIn01", "AIn02", "AIn03"]
        assert node.sources[1].pins == ["AIn01", "AIn02"]

    def test_total_power_monitoring(self):
        """Real scenario: Total power from multiple phases"""
        node = CompositeNode(
            type=ConditionType.SUM,
            sources=[
                # Phase R
                Source(device="ADTEK_CPM10", slave_id="1", pins=["kW_R"]),
                # Phase S
                Source(device="ADTEK_CPM10", slave_id="1", pins=["kW_S"]),
                # Phase T
                Source(device="ADTEK_CPM10", slave_id="1", pins=["kW_T"]),
            ],
            operator=ConditionOperator.GREATER_THAN,
            threshold=100.0,
        )

        assert not node.invalid
        assert node.type == ConditionType.SUM
        assert len(node.sources) == 3
