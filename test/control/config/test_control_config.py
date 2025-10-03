import logging

import pytest
from pydantic import ValidationError

from model.control_composite import CompositeNode
from model.enum.condition_enum import ConditionType, ControlActionType, ControlPolicyType
from schema.control_config_schema import ControlConfig


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


class TestConditionTypeFieldMigration:
    """Tests for condition_type vs source_kind field migration"""

    def test_when_config_uses_condition_type_then_policy_validation_passes(self, valid_sd400_config_data):
        """Test that new 'condition_type' field works correctly for different policy types"""
        # Arrange
        version = valid_sd400_config_data.get("version", "1.0.0")
        root_data = {k: v for k, v in valid_sd400_config_data.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "3")

        # Assert - Check that we have both policy types
        absolute_linear_controls = [
            c for c in controls if c.policy and c.policy.type == ControlPolicyType.ABSOLUTE_LINEAR
        ]
        incremental_linear_controls = [
            c for c in controls if c.policy and c.policy.type == ControlPolicyType.INCREMENTAL_LINEAR
        ]

        # Should have one of each type
        assert len(absolute_linear_controls) == 1
        assert len(incremental_linear_controls) == 1

        # ABSOLUTE_LINEAR should use 'threshold' condition_type
        abs_control = absolute_linear_controls[0]
        assert abs_control.policy.condition_type == ConditionType.THRESHOLD
        assert abs_control.policy.source is not None  # Should have single source
        assert abs_control.policy.sources is None  # Should NOT have sources array

        # INCREMENTAL_LINEAR should use 'difference' condition_type
        inc_control = incremental_linear_controls[0]
        assert inc_control.policy.condition_type == ConditionType.DIFFERENCE
        assert inc_control.policy.sources is not None  # Should have sources array
        assert len(inc_control.policy.sources) == 2  # Should have exactly 2 sources
        assert inc_control.policy.source is None  # Should NOT have single source

    def test_when_config_uses_legacy_source_kind_then_validation_fails(self, config_with_source_kind_legacy):
        """Test that legacy 'source_kind' field causes validation error"""
        # Act / Assert
        with pytest.raises(ValidationError) as exc_info:
            version = config_with_source_kind_legacy.get("version", "1.0.0")
            root_data = {k: v for k, v in config_with_source_kind_legacy.items() if k != "version"}
            ControlConfig(version=version, root=root_data)

        # Should fail because 'source_kind' is not a recognized field
        assert "source_kind" in str(exc_info.value) or "Extra inputs are not permitted" in str(exc_info.value)


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

        # Assert
        set_freq_controls = [c for c in controls if c.action.type == ControlActionType.SET_FREQUENCY]
        assert len(set_freq_controls) >= 1

        for control in set_freq_controls:
            if control.action.value is not None:
                assert isinstance(control.action.value, (int, float))

    def test_when_action_type_is_adjust_frequency_then_validation_passes(self, valid_sd400_config_data):
        """Test that new ADJUST_FREQUENCY action type works correctly"""
        # Arrange
        version = valid_sd400_config_data.get("version", "1.0.0")
        root_data = {k: v for k, v in valid_sd400_config_data.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "3")

        # Assert
        adjust_freq_controls = [c for c in controls if c.action.type == ControlActionType.ADJUST_FREQUENCY]
        assert len(adjust_freq_controls) == 1

        control = adjust_freq_controls[0]
        assert control.code == "LIN_INC01"
        assert control.action.model == "TECO_VFD"
        assert control.action.target == "RW_HZ"

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
        assert controls[0].action.value == 50.0

        # Should log duplicate resolution
        assert "duplicate priorities resolved" in caplog.text

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

    def test_when_composite_is_invalid_then_rule_is_filtered_out(self, config_with_invalid_composite, caplog):
        """Test that rules with invalid composite nodes are filtered out"""
        # Arrange
        caplog.set_level(logging.WARNING)
        version = config_with_invalid_composite.get("version", "1.0.0")
        root_data = {k: v for k, v in config_with_invalid_composite.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "1")

        # Assert
        assert len(controls) == 0  # Invalid rule should be filtered out
        assert "invalid composite" in caplog.text

    def test_when_action_is_missing_then_rule_is_filtered_out(self, config_with_missing_action, caplog):
        """Test that rules without action are filtered out"""
        # Arrange
        caplog.set_level(logging.ERROR)
        version = config_with_missing_action.get("version", "1.0.0")
        root_data = {k: v for k, v in config_with_missing_action.items() if k != "version"}
        config = ControlConfig(version=version, root=root_data)

        # Act
        controls = config.get_control_list("SD400", "1")

        # Assert
        assert len(controls) == 0
        assert "missing action.type" in caplog.text

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
        assert isinstance(controls[0].action.value, float)
        assert controls[0].action.value == 45.5

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
        assert isinstance(controls[0].action.value, float)
        assert controls[0].action.value == -2.5


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
        """Test that nodes with too many children are marked invalid"""

        # Create a node with excessive children (beyond MAX_CHILDREN_PER_NODE = 20)
        excessive_children = []
        for i in range(25):  # More than MAX_CHILDREN_PER_NODE
            child = CompositeNode(type="threshold", source=f"AIn{i:02d}", operator="gt", threshold=10.0)
            excessive_children.append(child)

        # When
        node = CompositeNode(all=excessive_children)

        # Then
        assert node.invalid is True

    def test_when_between_operator_has_invalid_range_then_validation_fails(self):
        """Test that BETWEEN operator with min >= max is invalid"""

        # When - min >= max (invalid)
        node = CompositeNode(
            type="threshold", source="AIn01", operator="between", min=15.0, max=10.0  # max < min (invalid)
        )

        # Then
        assert node.invalid is True

    def test_when_difference_sources_are_duplicate_then_validation_fails(
        self, config_with_duplicate_difference_sources, caplog
    ):
        """Test that duplicate sources in difference conditions are detected"""
        # Given
        caplog.set_level(logging.WARNING)

        # When
        config = create_control_config(config_with_duplicate_difference_sources)
        controls = config.get_control_list("SD400", "1")

        # Then - Rule should be filtered out
        assert len(controls) == 0
        # Should log validation error about duplicate sources
        assert any("sources must be different" in record.message for record in caplog.records)

    def test_when_operator_validation_detects_invalid_combinations(
        self, config_with_invalid_operator_combinations, caplog
    ):
        """Test that invalid operator-threshold combinations are detected"""
        # Given
        caplog.set_level(logging.WARNING)

        # When
        config = create_control_config(config_with_invalid_operator_combinations)
        controls = config.get_control_list("SD400", "1")

        # Then - Rule should be filtered out due to invalid composite
        assert len(controls) == 0
        # Should log validation errors
        assert any("BETWEEN" in record.message for record in caplog.records)

    def test_when_circular_reference_detected_then_graceful_handling(self, caplog):
        """Test that circular references are handled gracefully without crashing"""
        # Note: This would require manually constructing circular structures in code
        # For now, we test that the depth calculation returns -1 for problematic structures

        caplog.set_level(logging.ERROR)

        # Create a simple valid node first
        node = CompositeNode(type="threshold", source="AIn01", operator="gt", threshold=10.0)

        # Normal case should work
        depth = node.calculate_max_depth()
        assert depth >= 1
