"""
PARIKA Brain Response

Defines the immutable BrainResponse produced by Brain for a
BrainRequest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from .goal_result import GoalResult


class RequestStatus(StrEnum):
    """
    Overall status of a BrainRequest.
    
    SUCCESS: All required goals succeeded and the final response/synthesis succeeded.
    PARTIAL_SUCCESS: One or more non-blocking/independent goals failed, but useful 
        work completed and the final synthesis/final response succeeded.
    FAILED: Planning/execution failed such that no usable final response can be 
        produced, or the final synthesis itself failed.
    """
    
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class BrainResponse:
    """
    Immutable final response produced by Brain.

    A BrainResponse reports the per-Goal outcome of supervising a
    BrainRequest to completion, together with an overall status indicator.
    """

    request_id: str
    """
    Identifier of the originating BrainRequest.
    """

    plan_id: str | None
    """
    Identifier of the ExecutionPlan produced for this request.

    None when planning itself failed before a plan could be produced.
    """

    results: tuple[GoalResult, ...]
    """
    Per-Goal outcomes, in planned execution order.
    """

    planning_failure: BaseException | None = None
    """
    Exception raised while producing the ExecutionPlan, if planning
    failed before any Goal could be attempted.
    """

    synthesis_goal_id: str | None = None
    """
    Identifier of the synthesis goal (typically chat.respond with depends_on),
    if any. Used to correctly determine status when synthesis fails.
    """

    completed_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when this response was produced.
    """

    @property
    def succeeded(self) -> bool:
        """
        Whether every Goal in this request completed successfully.
        
        This property is maintained for backward compatibility.
        For the new three-state semantic, use `status` instead.
        
        Returns False if planning failed entirely.
        """

        if self.planning_failure is not None:
            return False

        # No results means no goals succeeded
        if not self.results:
            return False

        return all(result.succeeded for result in self.results)

    @property
    def status(self) -> RequestStatus:
        """
        Three-state overall status of this request.
        
        - SUCCESS: All goals succeeded (no planning failure, all goals succeeded)
        - PARTIAL_SUCCESS: Synthesis succeeded but some independent goals failed
        - FAILED: Planning failed, or synthesis failed, or no synthesis and all goals failed
        """
        
        # Planning failure -> FAILED
        if self.planning_failure is not None:
            print("DEBUG BrainResponse.status: planning_failure -> FAILED")
            return RequestStatus.FAILED
        
        # No results -> FAILED (nothing completed)
        if not self.results:
            print("DEBUG BrainResponse.status: no results -> FAILED")
            return RequestStatus.FAILED
        
        # Check if there's a synthesis goal that produced a ChatResult
        has_synthesis_response = False
        synthesis_succeeded = False
        synthesis_failed = False
        all_succeeded = True
        any_succeeded = False
        
        for result in self.results:
            if result.succeeded:
                any_succeeded = True
            else:
                all_succeeded = False
            
            # Check for synthesis goal with ChatResult
            if result.response is not None:
                backend_response = result.response.outputs.get("result")
                from parika.core.provider_manager.chat_result import ChatResult
                if isinstance(backend_response, ChatResult):
                    has_synthesis_response = True
                    if result.succeeded:
                        synthesis_succeeded = True
                    else:
                        synthesis_failed = True
        
        print(f"DEBUG BrainResponse.status: has_synthesis_response={has_synthesis_response}, synthesis_succeeded={synthesis_succeeded}, synthesis_failed={synthesis_failed}, all_succeeded={all_succeeded}, any_succeeded={any_succeeded}")
        
        # If we have a synthesis_goal_id, check if that specific goal failed
        if self.synthesis_goal_id is not None and not has_synthesis_response:
            print(f"DEBUG BrainResponse.status: checking synthesis_goal_id={self.synthesis_goal_id} because no ChatResult")
            for result in self.results:
                if result.goal_id == self.synthesis_goal_id:
                    if not result.succeeded:
                        synthesis_failed = True
                    break
        
        # If synthesis failed, it's FAILED regardless of other goals
        if synthesis_failed:
            print("DEBUG BrainResponse.status: synthesis_failed -> FAILED")
            return RequestStatus.FAILED
        
        # If synthesis succeeded, it's at least PARTIAL_SUCCESS (or SUCCESS if all succeeded)
        if has_synthesis_response and synthesis_succeeded:
            print(f"DEBUG BrainResponse.status: synthesis succeeded, all_succeeded={all_succeeded}")
            if all_succeeded:
                return RequestStatus.SUCCESS
            else:
                return RequestStatus.PARTIAL_SUCCESS
        
        # No synthesis response (or no ChatResult from synthesis)
        if all_succeeded:
            print("DEBUG BrainResponse.status: all_succeeded -> SUCCESS")
            return RequestStatus.SUCCESS
        elif any_succeeded:
            # Some goals succeeded but no successful synthesis
            print("DEBUG BrainResponse.status: any_succeeded -> PARTIAL_SUCCESS")
            return RequestStatus.PARTIAL_SUCCESS
        else:
            print("DEBUG BrainResponse.status: none succeeded -> FAILED")
            return RequestStatus.FAILED
        if self.planning_failure is not None:
            return RequestStatus.FAILED
        
        # No results -> FAILED (nothing completed)
        if not self.results:
            return RequestStatus.FAILED
        
        # Check if there's a synthesis goal that produced a ChatResult
        has_synthesis_response = False
        synthesis_succeeded = False
        synthesis_failed = False
        all_succeeded = True
        any_succeeded = False
        
        for result in self.results:
            if result.succeeded:
                any_succeeded = True
            else:
                all_succeeded = False
            
            # Check for synthesis goal with ChatResult
            if result.response is not None:
                backend_response = result.response.outputs.get("result")
                from parika.core.provider_manager.chat_result import ChatResult
                if isinstance(backend_response, ChatResult):
                    has_synthesis_response = True
                    if result.succeeded:
                        synthesis_succeeded = True
                    else:
                        synthesis_failed = True
        
        # If we have a synthesis_goal_id, check if that specific goal failed
        if self.synthesis_goal_id is not None and not has_synthesis_response:
            # Synthesis goal didn't produce a ChatResult - check if it failed
            for result in self.results:
                if result.goal_id == self.synthesis_goal_id:
                    if not result.succeeded:
                        synthesis_failed = True
                    break
        
        # If synthesis failed, it's FAILED regardless of other goals
        if synthesis_failed:
            return RequestStatus.FAILED
        
        # If synthesis succeeded, it's at least PARTIAL_SUCCESS (or SUCCESS if all succeeded)
        if has_synthesis_response and synthesis_succeeded:
            if all_succeeded:
                return RequestStatus.SUCCESS
            else:
                return RequestStatus.PARTIAL_SUCCESS
        
        # No synthesis response (or no ChatResult from synthesis)
        if all_succeeded:
            return RequestStatus.SUCCESS
        elif any_succeeded:
            # Some goals succeeded but no successful synthesis
            return RequestStatus.PARTIAL_SUCCESS
        else:
            return RequestStatus.FAILED

    @property
    def partial_success(self) -> bool:
        """
        Whether this request achieved partial success.
        
        This property is maintained for backward compatibility.
        For the new three-state semantic, use `status` instead.
        """
        return self.status == RequestStatus.PARTIAL_SUCCESS
