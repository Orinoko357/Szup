"""Shared Pydantic base model that converts empty strings to None."""
from __future__ import annotations
from pydantic import BaseModel, model_validator


class BaseSchema(BaseModel):
    """Base schema that coerces empty strings to None for all fields."""

    @model_validator(mode='before')
    @classmethod
    def convert_empty_strings(cls, data):
        if isinstance(data, dict):
            return {
                k: (None if v == '' else v)
                for k, v in data.items()
            }
        return data
