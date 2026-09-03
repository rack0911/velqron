from src.agents.base_agent import ExpertAgent


class RemediationAdvisor(ExpertAgent):
    """
    Expert Agent focused on recommending specific operational adjustments
    to mitigate identified stress or prevent imminent failure.
    """

    def __init__(self):
        super().__init__("Remediation Advisor")

    def analyze(self, data):
        """
        Input data should include the current diagnosis/event.
        """
        event = data.get("event", "NORMAL")

        remediations = {
            "Overload": "Limit current to 90% of rated FLA. Check for mechanical jamming in load path.",
            "Underload": "Inspect for coupling failure or dry-run condition. Verify intake supply.",
            "Winding Stress": "Cap RPM to 1200. Allow 30min cooling interval between cycles.",
            "Bearing Wear": "Schedule lubrication within 48h. Monitor vibration velocity peaks.",
            "Thermal Drift": "Clean cooling fins. Check ambient ventilation and fan operation.",
        }

        action = remediations.get(event, "No immediate operational changes required.")

        return {
            "agent": self.name,
            "severity": "INFO",
            "action": action,
            "reasoning": f"Based on {event} detection, the following mitigation is recommended to extend asset life.",
        }
