import base64
import io

try:
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


def generate_thermal_gradient_plot(currents: list, temps: list, ambient: float = 25.0):
    """
    Generates a placeholder thermal gradient visualization.
    Shows the predicted winding temp vs measured surface temp.
    """
    if not HAS_MATPLOTLIB or not currents or not temps:
        return None

    try:
        plt.figure(figsize=(10, 4))
        plt.plot(temps, label="Measured Surface Temp", color="blue")

        # Placeholder for predicted winding temp (higher than surface)
        predicted_winding = [t * 1.15 for t in temps]
        plt.plot(
            predicted_winding,
            label="Predicted Winding Temp (Thermal Model)",
            color="red",
            linestyle="--",
        )

        plt.axhline(y=ambient, color="green", linestyle=":", label="Ambient Baseline")
        plt.title("Motor Thermal Gradient Analysis")
        plt.xlabel("Cycle Progress (%)")
        plt.ylabel("Temperature (°C)")
        plt.legend()
        plt.grid(True, alpha=0.3)

        # Save to base64 for web display
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        buf.seek(0)
        img_str = base64.b64encode(buf.read()).decode("utf-8")
        plt.close()

        return img_str
    except Exception:
        plt.close()
        return None
