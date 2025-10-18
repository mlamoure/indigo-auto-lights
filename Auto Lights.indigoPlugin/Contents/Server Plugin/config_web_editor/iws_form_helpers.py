"""
IWS Form Helpers - WTForms without Flask

This module provides form generation utilities for IWS mode, using WTForms
without Flask dependencies. Forms are used for validation and rendering in
templates.
"""

from collections import OrderedDict
from wtforms import (
    Form, FormField, SubmitField, StringField, IntegerField,
    DecimalField, BooleanField, SelectField, SelectMultipleField
)
from wtforms.validators import DataRequired, Optional


def create_field(field_name, field_schema):
    """
    Create a WTForms field based on JSON schema definition.

    Args:
        field_name: Name of the field
        field_schema: JSON schema for this field

    Returns:
        WTForms field instance
    """
    label_text = field_schema.get("title", field_name)
    tooltip_text = field_schema.get("tooltip", "")
    field_type = field_schema.get("type")
    required = field_schema.get("required", False)

    validators = []
    if required:
        validators.append(DataRequired())
    else:
        validators.append(Optional())

    # Special handling for variable ID dropdowns
    if field_name.endswith("_var_id") and field_schema.get("x-drop-down"):
        choices = []
        if not required:
            choices.insert(0, (-1, "None Selected"))
        f = SelectField(label=label_text, description=tooltip_text, choices=choices, coerce=int, validators=validators)

    # Special handling for device ID multi-select
    elif field_name.endswith("_dev_ids") and field_schema.get("x-drop-down"):
        choices = []
        f = SelectMultipleField(label=label_text, description=tooltip_text, choices=choices, coerce=int, validators=validators)

    # Integer fields
    elif field_type == "integer":
        f = IntegerField(label=label_text, description=tooltip_text, validators=validators)

    # Number/decimal fields
    elif field_type == "number":
        f = DecimalField(label=label_text, description=tooltip_text, validators=validators)

    # Boolean fields
    elif field_type == "boolean":
        f = BooleanField(label=label_text, description=tooltip_text)

    # Enum select fields
    elif field_type == "string" and field_schema.get("enum"):
        enum_values = field_schema.get("enum", [])
        choices = [(val, val) for val in enum_values]
        f = SelectField(label=label_text, description=tooltip_text, choices=choices, validators=validators)

    # Default string field
    else:
        f = StringField(label=label_text, description=tooltip_text, validators=validators)

    f.description = tooltip_text
    return f


def generate_form_class_from_schema(schema):
    """
    Dynamically generate a WTForms Form class from a JSON schema.

    This is the IWS equivalent of the Flask version, using Form instead of FlaskForm.

    Args:
        schema: JSON schema definition

    Returns:
        Dynamically generated Form class
    """
    attrs = OrderedDict()

    for prop, subschema in schema.get("properties", {}).items():
        subschema["required"] = (prop in schema.get("required", []))

        # Nested object becomes a FormField
        if subschema.get("type") == "object":
            subform_class = generate_form_class_from_schema(subschema)
            attrs[prop] = FormField(subform_class, label=subschema.get("title", prop))
        else:
            attrs[prop] = create_field(prop, subschema)

    # Create a base Form class (not FlaskForm - no CSRF needed)
    class DynamicForm(Form):
        pass

    return type("DynamicForm", (DynamicForm,), attrs)


def populate_form_from_dict(form, data):
    """
    Populate a WTForms form instance with data from a dictionary.

    Args:
        form: WTForms Form instance
        data: Dictionary of field values
    """
    for field_name, field in form._fields.items():
        if field_name in data:
            field.data = data[field_name]


def extract_form_data(form):
    """
    Extract data from a WTForms form into a dictionary.

    Args:
        form: WTForms Form instance

    Returns:
        Dictionary of field_name: field_value
    """
    return {
        field_name: field.data
        for field_name, field in form._fields.items()
        if field_name != "submit"
    }
