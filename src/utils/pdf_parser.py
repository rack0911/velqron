import re

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    class PdfReader:
        def __init__(self, *args, **kwargs):
            raise ImportError("pypdf is not installed. Please install it to parse PDFs.")
    HAS_PYPDF = False

from src.utils.logger import get_logger

logger = get_logger(__name__)


def parse_motor_datasheet(pdf_path):
    """
    Parses a motor manufacturer datasheet PDF using pypdf.
    Extracts key fields: rated_current, service_factor, insulation_class, max_temp_c, manufacturer, model.
    """
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"

        logger.info(f"PDF Parser: Extracted {len(text)} characters from {pdf_path}")

        # Regex extraction
        results = {}

        # 1. Rated Current / FLA (e.g. FLA: 1.5 A, Rated Current: 2.3 Amps, Current = 1.8)
        current_match = re.search(
            r"(?:rated\s+current|current|fla|full\s+load\s+amps)(?:\s*[:=]\s*|\s+)(\d+(?:\.\d+)?)\s*(?:a|amps)?",
            text,
            re.IGNORECASE,
        )
        if current_match:
            results["rated_current"] = float(current_match.group(1))

        # 2. Service Factor (e.g. Service Factor: 1.15, SF = 1.0)
        sf_match = re.search(
            r"(?:service\s+factor|sf)(?:\s*[:=]\s*|\s+)(\d+(?:\.\d+)?)(?!\s*a|amps|v|w|kw|hz)",
            text,
            re.IGNORECASE,
        )
        if sf_match:
            results["service_factor"] = float(sf_match.group(1))

        # 3. Insulation Class (e.g. Insulation Class: F, Class H)
        ins_match = re.search(
            r"(?:insulation\s+class|ins\.\s+cl\.|class)(?:\s*[:=]\s*|\s+)([A-H])\b",
            text,
            re.IGNORECASE,
        )
        if ins_match:
            results["insulation_class"] = ins_match.group(1).upper()
            # Map insulation class to standard industry temp limits
            ins_temp_map = {"A": 105.0, "E": 120.0, "B": 130.0, "F": 155.0, "H": 180.0}
            results["max_temp_c"] = ins_temp_map.get(results["insulation_class"], 125.0)

        # 4. Max Temperature explicit match (e.g. Max Temp: 125 C, 155°C)
        temp_match = re.search(
            r"(?:max\s*temp|temperature\s+limit|max\.\s+temp)(?:\s*[:=]\s*|\s+)(\d+(?:\.\d+)?)\s*(?:°?\s*c|celsius)?",
            text,
            re.IGNORECASE,
        )
        if temp_match:
            results["max_temp_c"] = float(temp_match.group(1))

        # 5. Manufacturer / Model
        mfr_match = re.search(
            r"(?:manufacturer|make|brand)(?:\s*[:=]\s*|\s+)([a-zA-Z0-9\s\-\.\_]+)",
            text,
            re.IGNORECASE,
        )
        if mfr_match:
            results["make"] = mfr_match.group(1).strip().split("\n")[0]

        model_match = re.search(
            r"(?:model|type|cat\s+no|frame)(?:\s*[:=]\s*|\s+)([a-zA-Z0-9\-\/]+)",
            text,
            re.IGNORECASE,
        )
        if model_match:
            results["model"] = model_match.group(1).strip().split("\n")[0]

        logger.info(f"PDF Parser: Extracted fields: {results}")
        return results

    except Exception as e:
        logger.error(f"PDF Parser: Failed to parse {pdf_path}: {e}", exc_info=True)
        return {}
