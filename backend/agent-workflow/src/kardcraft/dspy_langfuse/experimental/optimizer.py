"""DSPy optimizer integration with Langfuse."""

from __future__ import annotations

from typing import Any, Callable, Optional, Type

import dspy

from kardcraft.utils.logger import logger
from .version_manager import PromptVersionManager, get_version_manager


class OptimizerPipeline:
    """
    Pipeline for running DSPy optimization with Langfuse integration.

    Features:
    - Support for MIPROv2, BootstrapFewShot and other optimizers
    - Automatic version publishing
    - Multi-language optimization
    - Training data management
    """

    def __init__(
        self,
        version_manager: PromptVersionManager = None,
    ):
        self.version_manager = version_manager or get_version_manager()

    def optimize(
        self,
        module_class: Type[dspy.Module],
        trainset: list,
        metric: Callable,
        valset: list = None,
        optimizer_type: str = "mipro_v2",
        module_name: str = None,
        **optimizer_kwargs,
    ) -> tuple[dspy.Module, float]:
        """
        Run optimization on a module.

        Args:
            module_class: DSPy module class to optimize
            trainset: Training examples
            metric: Evaluation metric
            valset: Validation examples
            optimizer_type: Type of optimizer ("mipro_v2", "bootstrap", "fewshot")
            module_name: Name for version management
            **optimizer_kwargs: Additional optimizer arguments

        Returns:
            (compiled_module, evaluation_score)
        """
        module_name = module_name or module_class.__name__
        valset = valset or trainset[: min(20, len(trainset))]

        logger.info(f"Starting {optimizer_type} optimization for {module_name}")
        logger.info(
            f"Training set: {len(trainset)} examples, validation set: {len(valset)} examples"
        )

        optimizer = self._get_optimizer(optimizer_type, metric, **optimizer_kwargs)
        module = module_class()

        compiled = optimizer.compile(
            module,
            trainset=trainset,
            valset=valset,
        )

        score = self._evaluate(compiled, valset)
        logger.info(f"Optimization complete. Score: {score:.3f}")

        return compiled, score

    def optimize_and_publish(
        self,
        module_class: Type[dspy.Module],
        trainset: list,
        metric: Callable,
        module_name: str,
        valset: list = None,
        optimizer_type: str = "mipro_v2",
        publish: bool = True,
        **optimizer_kwargs,
    ) -> tuple[dspy.Module, float, Any]:
        """
        Optimize and optionally publish to Langfuse.

        Args:
            module_class: DSPy module class
            trainset: Training examples
            metric: Evaluation metric
            module_name: Name for Langfuse
            valset: Validation examples
            optimizer_type: Optimizer type
            publish: Whether to publish to Langfuse
            **optimizer_kwargs: Additional optimizer arguments

        Returns:
            (compiled_module, score, prompt_object_or_none)
        """
        compiled, score = self.optimize(
            module_class,
            trainset,
            metric,
            valset,
            optimizer_type,
            module_name,
            **optimizer_kwargs,
        )

        prompt_obj = None
        if publish:
            prompt = self._extract_prompt(compiled)
            prompt_obj = self.version_manager.publish_prompt(
                module_name=module_name,
                prompt=prompt,
                metric_score=score,
                labels=["staging"],
                config={"optimizer": optimizer_type, "train_samples": len(trainset)},
            )

        return compiled, score, prompt_obj

    def _get_optimizer(
        self,
        optimizer_type: str,
        metric: Callable,
        **kwargs,
    ) -> Any:
        """Get the appropriate optimizer instance."""
        optimizer_type = optimizer_type.lower()

        if optimizer_type == "mipro_v2":
            return dspy.MIPROv2(
                metric=metric,
                auto=kwargs.get("auto", "light"),
                num_candidates=kwargs.get("num_candidates", 10),
            )
        elif optimizer_type == "bootstrap" or optimizer_type == "bootstrap_fewshot":
            return dspy.BootstrapFewShot(
                metric=metric,
                max_bootstrapped_demos=kwargs.get("max_demos", 4),
                max_labeled_demos=kwargs.get("max_demos", 4),
            )
        elif optimizer_type == "fewshot":
            return dspy.LabeledFewShot(kwargs.get("n demos", 4))
        else:
            logger.warning(f"Unknown optimizer {optimizer_type}, using MIPROv2")
            return dspy.MIPROv2(metric=metric)

    def _evaluate(self, module: dspy.Module, valset: list) -> float:
        """Evaluate module on validation set."""
        correct = 0
        for example in valset:
            try:
                pred = module(
                    **{k: v for k, v in example.items() if k != "ground_truth"}
                )
                if hasattr(pred, "answer") and hasattr(example, "ground_truth"):
                    if pred.answer == example.ground_truth:
                        correct += 1
            except Exception:
                pass

        return correct / len(valset) if valset else 0.0

    def _extract_prompt(self, module: dspy.Module) -> str:
        """Extract prompt from compiled module."""
        if hasattr(module, "signature") and module.signature:
            return module.signature.__doc__ or ""
        return str(module)


class MultilingualOptimizer:
    """
    Optimizer that handles multiple languages separately.

    Each language gets its own optimization run and version in Langfuse.
    """

    def __init__(
        self,
        base_module_class: Type[dspy.Module],
        base_module_name: str,
        version_manager: PromptVersionManager = None,
    ):
        self.base_module_class = base_module_class
        self.base_module_name = base_module_name
        self.version_manager = version_manager or get_version_manager()
        self.pipeline = OptimizerPipeline(version_manager=self.version_manager)

    def optimize_language(
        self,
        language: str,
        trainset: list,
        metric: Callable,
        valset: list = None,
    ) -> tuple[dspy.Module, float]:
        """
        Optimize for a specific language.

        Args:
            language: Language code (e.g., "zh", "en")
            trainset: Language-specific training data
            metric: Evaluation metric
            valset: Validation data

        Returns:
            (compiled_module, score)
        """
        module_name = f"{self.base_module_name}_{language}"

        logger.info(f"Optimizing {module_name} with {len(trainset)} examples")

        return self.pipeline.optimize_and_publish(
            self.base_module_class,
            trainset,
            metric,
            module_name,
            valset,
            publish=True,
        )[:2]

    def optimize_all(
        self,
        language_datasets: dict[str, list],
        metric: Callable,
    ) -> dict[str, tuple[dspy.Module, float]]:
        """
        Optimize for all languages in the dataset.

        Args:
            language_datasets: Dict mapping language code to training data
            metric: Evaluation metric

        Returns:
            Dict mapping language to (module, score)
        """
        results = {}

        for lang, trainset in language_datasets.items():
            try:
                module, score = self.optimize_language(lang, trainset, metric)
                results[lang] = (module, score)
            except Exception as e:
                logger.error(f"Failed to optimize for {lang}: {e}")

        return results


def create_optimizer_pipeline() -> OptimizerPipeline:
    """Create a default optimizer pipeline."""
    return OptimizerPipeline()
