"""
PARIKA Expense Module - Manifest

Defines the static ModuleManifest describing the Expense Management
Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import ExpenseModuleDriver

EXPENSE_MODULE_ID = "expense"
EXPENSE_MODULE_VERSION = "1.0.0"


def create_expense_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Expense Management
    Module.
    """

    return ModuleManifest(
        id=EXPENSE_MODULE_ID,
        name="Expense Management",
        version=EXPENSE_MODULE_VERSION,
        description=(
            "Provides the expense.add_expense, expense.get_expense, "
            "expense.list_expenses, expense.update_expense, "
            "expense.remove_expense, expense.summarize_expenses, and "
            "expense.compare_periods Capabilities for tracking, "
            "querying, and summarizing personal expenses, backed by "
            "PARIKA's own SQLite persistence."
        ),
        author="PARIKA",
        license="MIT",
        tags=("expense", "finance", "personal"),
        driver="parika.modules.expense.driver.ExpenseModuleDriver",
    )


def create_expense_module(driver: ExpenseModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Expense Management
    Module.
    """

    return Module(
        id=EXPENSE_MODULE_ID,
        manifest=create_expense_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
