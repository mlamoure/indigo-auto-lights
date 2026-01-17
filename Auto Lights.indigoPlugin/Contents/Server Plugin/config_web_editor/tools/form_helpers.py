from collections import OrderedDict
from flask_wtf import FlaskForm
from wtforms import FormField, SubmitField, StringField, IntegerField, DecimalField, BooleanField, SelectField, SelectMultipleField
from wtforms.validators import DataRequired

def create_field(field_name, field_schema):
    label_text = field_schema.get("title", field_name)
    tooltip_text = field_schema.get("tooltip", "")
    field_type = field_schema.get("type")
    if field_name.endswith("_var_id") and field_schema.get("x-drop-down"):
        # For demonstration; adjust to fetch actual choices as needed.
        choices = []
        if not field_schema.get("required"):
            choices.insert(0, (-1, "None Selected"))
        f = SelectField(label=label_text, description=tooltip_text, choices=choices, coerce=int)
    elif field_name.endswith("_dev_ids") and field_schema.get("x-drop-down"):
        choices = []
        f = SelectMultipleField(label=label_text, description=tooltip_text, choices=choices, coerce=int)
    elif field_type == "integer":
        f = IntegerField(label=label_text, description=tooltip_text, validators=[DataRequired()])
    elif field_type == "number":
        f = DecimalField(label=label_text, description=tooltip_text, validators=[DataRequired()])
    elif field_type == "boolean":
        f = BooleanField(label=label_text, description=tooltip_text)
    elif field_type == "string" and field_schema.get("enum"):
        enum_values = field_schema.get("enum", [])
        choices = [(val, val) for val in enum_values]
        f = SelectField(label=label_text, description=tooltip_text, choices=choices)
    else:
        f = StringField(label=label_text, description=tooltip_text, validators=[DataRequired()])
    f.description = tooltip_text
    return f

def generate_form_class_from_schema(schema):
    attrs = OrderedDict()
    for prop, subschema in schema.get("properties", {}).items():
        subschema["required"] = (prop in schema.get("required", []))
        if subschema.get("type") == "object":
            subform_class = generate_form_class_from_schema(subschema)
            attrs[prop] = FormField(subform_class, label=subschema.get("title", prop))
        else:
            attrs[prop] = create_field(prop, subschema)
    class DynamicFormNoCSRF(FlaskForm):
        class Meta:
            csrf = False
    return type("DynamicFormNoCSRF", (DynamicFormNoCSRF,), attrs)
