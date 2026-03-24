"""Signature factory for managing DSPy signatures."""

import os
from functools import lru_cache
from typing import Any, Callable, Dict, Optional, Type

import dspy

from kardcraft.utils.logger import logger


class SignatureFactory:
    """
    Factory for creating and managing DSPy signatures with multilingual support.

    Features:
    - Signature creation with instructions
    - Multilingual instruction mapping
    - Caching for performance
    - Signature inheritance
    """

    def __init__(self):
        self._custom_signatures: Dict[str, Type[dspy.Signature]] = {}
        self._instruction_cache: Dict[str, Dict[str, str]] = {}

    def register_instructions(
        self,
        base_name: str,
        instructions: Dict[str, str],
    ):
        """
        Register multilingual instructions for a signature.

        Args:
            base_name: Base name for the signature
            instructions: Dict mapping lang code to instructions
        """
        self._instruction_cache[base_name] = instructions

    def get_instruction(self, base_name: str, lang: str = "en") -> str:
        """
        Get instructions for a specific language.

        Args:
            base_name: Base name of the signature
            lang: Language code

        Returns:
            Instructions string
        """
        if base_name in self._instruction_cache:
            instructions = self._instruction_cache[base_name]
            return instructions.get(lang, instructions.get("en", ""))

        return ""

    def create_signature(
        self,
        name: str,
        base_signature: Type[dspy.Signature],
        lang: str = "en",
        instructions: str = None,
    ) -> Type[dspy.Signature]:
        """
        Create a signature with specified language instructions.

        Args:
            name: Unique name for the signature
            base_signature: Base signature class to extend
            lang: Language code
            instructions: Custom instructions, or None to use registered

        Returns:
            New signature class with instructions
        """
        instructions = instructions or self.get_instruction(name, lang)

        if not instructions and base_signature.__doc__:
            instructions = base_signature.__doc__

        key = f"{name}_{lang}"
        if key in self._custom_signatures:
            return self._custom_signatures[key]

        if instructions:
            signature = base_signature.with_instructions(instructions)
        else:
            signature = base_signature

        self._custom_signatures[key] = signature
        return signature

    def create_field_signature(
        self,
        name: str,
        input_fields: Dict[str, Any],
        output_fields: Dict[str, Any],
        instructions: str = None,
    ) -> Type[dspy.Signature]:
        """
        Create a signature from field definitions.

        Args:
            name: Signature name
            input_fields: Dict of input field definitions
            output_fields: Dict of output field definitions
            instructions: Optional instructions

        Returns:
            New signature class
        """
        key = f"{name}_custom"
        if key in self._custom_signatures:
            return self._custom_signatures[key]

        class CustomSignature(dspy.Signature):
            __doc__ = instructions or ""
            pass

        for field_name, field_def in input_fields.items():
            if isinstance(field_def, dict):
                setattr(CustomSignature, field_name, dspy.InputField(**field_def))
            else:
                setattr(
                    CustomSignature, field_name, dspy.InputField(desc=str(field_def))
                )

        for field_name, field_def in output_fields.items():
            if isinstance(field_def, dict):
                setattr(CustomSignature, field_name, dspy.OutputField(**field_def))
            else:
                setattr(
                    CustomSignature, field_name, dspy.OutputField(desc=str(field_def))
                )

        self._custom_signatures[key] = CustomSignature
        return CustomSignature

    def clear_cache(self):
        """Clear the signature cache."""
        self._custom_signatures.clear()


def create_multilingual_signature(
    name: str,
    input_fields: Dict[str, Any],
    output_fields: Dict[str, Any],
    instructions: Dict[str, str],
    lang: str = "en",
) -> Type[dspy.Signature]:
    """
    Convenience function to create a multilingual signature.

    Args:
        name: Signature name
        input_fields: Input field definitions
        output_fields: Output field definitions
        instructions: Multilingual instructions dict
        lang: Language to use

    Returns:
        Signature class
    """
    factory = SignatureFactory()
    factory.register_instructions(name, instructions)
    return factory.create_signature(
        name,
        create_basic_signature(name, input_fields, output_fields),
        lang=lang,
    )


def create_basic_signature(
    name: str,
    input_fields: Dict[str, Any],
    output_fields: Dict[str, Any],
) -> Type[dspy.Signature]:
    """
    Create a basic signature from field definitions.

    Args:
        name: Signature name
        input_fields: Input fields
        output_fields: Output fields

    Returns:
        Signature class
    """

    class BasicSignature(dspy.Signature):
        pass

    for field_name, field_def in input_fields.items():
        if isinstance(field_def, dict):
            setattr(BasicSignature, field_name, dspy.InputField(**field_def))
        else:
            setattr(BasicSignature, field_name, dspy.InputField(desc=str(field_def)))

    for field_name, field_def in output_fields.items():
        if isinstance(field_def, dict):
            setattr(BasicSignature, field_name, dspy.OutputField(**field_def))
        else:
            setattr(BasicSignature, field_name, dspy.OutputField(desc=str(field_def)))

    BasicSignature.__name__ = name
    return BasicSignature


@lru_cache(maxsize=32)
def get_cached_signature(
    name: str,
    lang: str,
    instructions_json: str,
) -> Type[dspy.Signature]:
    """
    Get a cached signature (for use with stable instruction sets).

    Args:
        name: Signature name
        lang: Language code
        instructions_json: JSON string of instructions

    Returns:
        Signature class
    """
    import json

    instructions = json.loads(instructions_json) if instructions_json else {}
    lang_instructions = instructions.get(lang, instructions.get("en", ""))

    class CachedSignature(dspy.Signature):
        __doc__ = lang_instructions

    CachedSignature.__name__ = f"{name}_{lang}"
    return CachedSignature


_default_factory: Optional[SignatureFactory] = None


def get_signature_factory() -> SignatureFactory:
    """Get the default signature factory instance."""
    global _default_factory
    if _default_factory is None:
        _default_factory = SignatureFactory()
    return _default_factory
