"""
Enhanced Evidence Card System for OfficeQA

Extends ROMA's evidence card system with:
- Automated validation against scorer logic
- Skill-based verification and correction
- Cross-card consistency checking
- Confidence scoring and uncertainty quantification
"""

import json
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class CardType(Enum):
    RETRIEVE = "retrieve"
    THINK = "think"
    AGGREGATE = "aggregate"


class ConfidenceLevel(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class EvidenceCard:
    """Enhanced evidence card with validation metadata"""
    value: str
    card_type: CardType
    source_file: Optional[str] = None
    unit_header: Optional[str] = None
    base_number_only: bool = True
    page_hint: Optional[str] = None
    table_key: Optional[str] = None
    raw_snippet: Optional[str] = None
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    notes: str = ""
    
    # Enhanced fields
    validation_errors: List[str] = field(default_factory=list)
    cross_references: List[str] = field(default_factory=list)
    computation_method: Optional[str] = None
    computation_inputs: Dict[str, Any] = field(default_factory=dict)
    verification_status: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "value": self.value,
            "card_type": self.card_type.value,
            "source_file": self.source_file,
            "unit_header": self.unit_header,
            "base_number_only": self.base_number_only,
            "page_hint": self.page_hint,
            "table_key": self.table_key,
            "raw_snippet": self.raw_snippet,
            "confidence": self.confidence.value,
            "notes": self.notes,
            "validation_errors": self.validation_errors,
            "cross_references": self.cross_references,
            "computation_method": self.computation_method,
            "computation_inputs": self.computation_inputs,
            "verification_status": self.verification_status
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceCard":
        """Create from dictionary"""
        card = cls(
            value=data["value"],
            card_type=CardType(data["card_type"]),
            source_file=data.get("source_file"),
            unit_header=data.get("unit_header"),
            base_number_only=data.get("base_number_only", True),
            page_hint=data.get("page_hint"),
            table_key=data.get("table_key"),
            raw_snippet=data.get("raw_snippet"),
            confidence=ConfidenceLevel(data.get("confidence", "medium")),
            notes=data.get("notes", "")
        )
        card.validation_errors = data.get("validation_errors", [])
        card.cross_references = data.get("cross_references", [])
        card.computation_method = data.get("computation_method")
        card.computation_inputs = data.get("computation_inputs", {})
        card.verification_status = data.get("verification_status")
        return card


class EvidenceCardValidator:
    """Validates evidence cards against OfficeQA scorer logic"""
    
    def __init__(self):
        self.unit_patterns = {
            "millions": r"million",
            "thousands": r"thousand", 
            "billions": r"billion",
            "percent": r"percent|%",
            "dollars": r"\$|dollar"
        }
    
    def validate_card(self, card: EvidenceCard) -> List[str]:
        """Validate a single evidence card and return errors"""
        errors = []
        
        # Base number validation
        if card.card_type == CardType.RETRIEVE:
            errors.extend(self._validate_base_number(card))
        
        # Unit consistency
        if card.unit_header:
            errors.extend(self._validate_unit_consistency(card))
        
        # Source validation
        if card.source_file:
            errors.extend(self._validate_source_reference(card))
        
        # Confidence justification
        if card.confidence == ConfidenceLevel.HIGH:
            errors.extend(self._validate_high_confidence(card))
        
        # Computation validation
        if card.card_type == CardType.THINK:
            errors.extend(self._validate_computation(card))
        
        card.validation_errors = errors
        return errors
    
    def _validate_base_number(self, card: EvidenceCard) -> List[str]:
        """Validate base number extraction"""
        errors = []
        
        # Check for common formatting issues
        if any(char in card.value for char in ['$', ',', '%']):
            errors.append("Value contains formatting characters ($, , or %)")
        
        # Check for unit expansion
        if card.unit_header and "million" in card.unit_header.lower():
            # If header says millions, value should be reasonable for millions
            try:
                val = float(card.value)
                if val > 1000000:  # Likely expanded incorrectly
                    errors.append("Value appears to expand units incorrectly")
            except ValueError:
                errors.append("Value is not a valid number")
        
        # Check for Unicode issues
        if '–' in card.value or '—' in card.value:
            errors.append("Unicode dash detected, use hyphen-minus")
        
        return errors
    
    def _validate_unit_consistency(self, card: EvidenceCard) -> List[str]:
        """Validate unit consistency"""
        errors = []
        
        if not card.unit_header:
            return errors
        
        # Check if value magnitude matches unit
        try:
            val = float(card.value)
            
            if "million" in card.unit_header.lower():
                if val < 1 or val > 100000:  # Unreasonable for millions
                    errors.append("Value magnitude inconsistent with 'millions' unit")
            elif "billion" in card.unit_header.lower():
                if val < 1000 or val > 10000000:  # Unreasonable for billions
                    errors.append("Value magnitude inconsistent with 'billions' unit")
            elif "percent" in card.unit_header.lower():
                if val < 0 or val > 100:  # Unreasonable for percentages
                    errors.append("Value magnitude inconsistent with 'percent' unit")
                    
        except ValueError:
            errors.append("Cannot validate unit consistency - invalid number")
        
        return errors
    
    def _validate_source_reference(self, card: EvidenceCard) -> List[str]:
        """Validate source file reference"""
        errors = []
        
        # Check filename format
        if card.source_file:
            if not re.match(r".*treasury_bulletin_\d{4}_\d{2}\.*", card.source_file):
                errors.append("Source filename doesn't match expected Treasury Bulletin format")
        
        return errors
    
    def _validate_high_confidence(self, card: EvidenceCard) -> List[str]:
        """Validate that high confidence is justified"""
        errors = []
        
        if card.confidence == ConfidenceLevel.HIGH:
            if not card.raw_snippet:
                errors.append("High confidence requires raw snippet for verification")
            
            if not card.table_key or "/" not in card.table_key:
                errors.append("High confidence requires precise row/column identification")
        
        return errors
    
    def _validate_computation(self, card: EvidenceCard) -> List[str]:
        """Validate computation cards"""
        errors = []
        
        if card.card_type == CardType.THINK:
            if not card.computation_method:
                errors.append("Computation cards must specify method")
            
            if not card.computation_inputs:
                errors.append("Computation cards must specify inputs")
        
        return errors


class EvidenceCardAggregator:
    """Aggregates multiple evidence cards with consistency checking"""
    
    def __init__(self, validator: EvidenceCardValidator):
        self.validator = validator
    
    def aggregate_cards(self, cards: List[EvidenceCard]) -> Tuple[Optional[EvidenceCard], List[str]]:
        """Aggregate multiple cards into final answer"""
        
        if not cards:
            return None, ["No evidence cards provided"]
        
        # Validate all cards
        all_errors = []
        for card in cards:
            card_errors = self.validator.validate_card(card)
            all_errors.extend([f"{card.table_key}: {err}" for err in card_errors])
        
        # Check cross-card consistency
        consistency_errors = self._check_consistency(cards)
        all_errors.extend(consistency_errors)
        
        # Aggregate based on card types
        if len(cards) == 1:
            return cards[0], all_errors
        
        # Multiple cards aggregation
        try:
            if all(card.card_type == CardType.RETRIEVE for card in cards):
                return self._aggregate_retrieve_cards(cards)
            elif any(card.card_type == CardType.THINK for card in cards):
                return self._aggregate_computation_cards(cards)
            else:
                return self._aggregate_mixed_cards(cards)
        except Exception as e:
            return None, all_errors + [f"Aggregation failed: {str(e)}"]
    
    def _check_consistency(self, cards: List[EvidenceCard]) -> List[str]:
        """Check consistency across multiple cards"""
        errors = []
        
        # Unit consistency
        unit_headers = [card.unit_header for card in cards if card.unit_header]
        if len(set(unit_headers)) > 1:
            errors.append(f"Inconsistent units across cards: {unit_headers}")
        
        # Source time consistency
        source_files = [card.source_file for card in cards if card.source_file]
        if source_files:
            # Extract years from filenames
            years = []
            for filename in source_files:
                match = re.search(r"treasury_bulletin_(\d{4})_", filename)
                if match:
                    years.append(int(match.group(1)))
            
            if len(set(years)) > 3:  # More than 3 years span might be wrong
                errors.append(f"Large year span in sources: {years}")
        
        # Confidence consistency
        low_conf_cards = [card for card in cards if card.confidence == ConfidenceLevel.LOW]
        if len(low_conf_cards) > len(cards) / 2:
            errors.append("Majority of cards have low confidence")
        
        return errors
    
    def _aggregate_retrieve_cards(self, cards: List[EvidenceCard]) -> Tuple[EvidenceCard, List[str]]:
        """Aggregate multiple retrieval cards"""
        errors = []
        
        if len(cards) == 1:
            return cards[0], errors
        
        # For multiple retrieve cards, this is likely a multi-number answer
        values = []
        all_sources = []
        
        for card in cards:
            try:
                val = float(card.value)
                values.append(val)
                all_sources.append(card.source_file)
            except ValueError:
                errors.append(f"Invalid numeric value in card: {card.value}")
        
        if errors:
            return None, errors
        
        # Create aggregated card
        aggregated = EvidenceCard(
            value=f"[{', '.join(str(v) for v in values)}]",
            card_type=CardType.AGGREGATE,
            confidence=self._aggregate_confidence(cards),
            notes=f"Aggregated from {len(cards)} sources: {', '.join(all_sources)}",
            cross_references=[f"Card_{i}" for i in range(len(cards))]
        )
        
        return aggregated, errors
    
    def _aggregate_computation_cards(self, cards: List[EvidenceCard]) -> Tuple[EvidenceCard, List[str]]:
        """Aggregate cards involving computation"""
        errors = []
        
        # Find the final computation result
        think_cards = [card for card in cards if card.card_type == CardType.THINK]
        retrieve_cards = [card for card in cards if card.card_type == CardType.RETRIEVE]
        
        if not think_cards:
            return None, ["No computation cards found"]
        
        # Use the last think card as the result
        result_card = think_cards[-1]
        
        # Add references to input cards
        result_card.cross_references = [f"Retrieve_{i}" for i in range(len(retrieve_cards))]
        
        # Aggregate confidence
        result_card.confidence = self._aggregate_confidence(cards)
        
        return result_card, errors
    
    def _aggregate_mixed_cards(self, cards: List[EvidenceCard]) -> Tuple[EvidenceCard, List[str]]:
        """Aggregate mixed card types"""
        errors = []
        
        # Find the primary result card
        # Priority: AGGREGATE > THINK > RETRIEVE
        primary = None
        for card_type in [CardType.AGGREGATE, CardType.THINK, CardType.RETRIEVE]:
            for card in reversed(cards):  # Last card of each type
                if card.card_type == card_type:
                    primary = card
                    break
            if primary:
                break
        
        if not primary:
            return None, ["Could not determine primary result card"]
        
        # Add cross-references
        primary.cross_references = [f"Card_{i}" for i, card in enumerate(cards) if card != primary]
        primary.confidence = self._aggregate_confidence(cards)
        
        return primary, errors
    
    def _aggregate_confidence(self, cards: List[EvidenceCard]) -> ConfidenceLevel:
        """Aggregate confidence levels"""
        confidences = [card.confidence for card in cards]
        
        if all(c == ConfidenceLevel.HIGH for c in confidences):
            return ConfidenceLevel.HIGH
        elif any(c == ConfidenceLevel.LOW for c in confidences):
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.MEDIUM


class SkillTriggeredEnhancer:
    """Enhances evidence cards using triggered skills"""
    
    def __init__(self, skills_path: Path):
        self.skills_path = skills_path
        self.loaded_skills = {}
        self._load_skills()
    
    def _load_skills(self):
        """Load available skills from skills directory"""
        if not self.skills_path.exists():
            return
        
        for skill_dir in self.skills_path.iterdir():
            if skill_dir.is_dir():
                metadata_file = skill_dir / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                    self.loaded_skills[skill_dir.name] = metadata
    
    def enhance_card(self, card: EvidenceCard) -> EvidenceCard:
        """Enhance a card using triggered skills"""
        
        # Find relevant skills based on card content
        triggered_skills = self._find_triggered_skills(card)
        
        for skill_name in triggered_skills:
            card = self._apply_skill(card, skill_name)
        
        return card
    
    def _find_triggered_skills(self, card: EvidenceCard) -> List[str]:
        """Find skills that should trigger for this card"""
        triggered = []
        
        card_text = " ".join(filter(None, [
            card.value,
            card.unit_header or "",
            card.table_key or "",
            card.notes or ""
        ])).lower()
        
        for skill_name, metadata in self.loaded_skills.items():
            triggers = metadata.get("triggers", [])
            for trigger in triggers:
                if trigger.lower() in card_text:
                    triggered.append(skill_name)
                    break
        
        return triggered
    
    def _apply_skill(self, card: EvidenceCard, skill_name: str) -> EvidenceCard:
        """Apply a skill to enhance a card"""
        
        skill_dir = self.skills_path / skill_name
        skill_file = skill_dir / f"{skill_name}.py"
        
        if not skill_file.exists():
            return card
        
        # Load and execute skill logic
        try:
            skill_code = skill_file.read_text()
            
            # Create skill namespace
            skill_namespace = {}
            exec(skill_code, skill_namespace)
            
            # Apply relevant skill functions
            if "check_unit_expansion" in skill_namespace and card.card_type == CardType.RETRIEVE:
                is_valid, message = skill_namespace["check_unit_expansion"](card.to_dict(), card.raw_snippet)
                if not is_valid:
                    card.validation_errors.append(f"Skill {skill_name}: {message}")
                    card.confidence = ConfidenceLevel.LOW
                else:
                    card.verification_status = f"Verified by {skill_name}"
            
            elif "resolve_fiscal_year" in skill_name and "fiscal" in card.table_key.lower():
                fiscal_result = skill_namespace["resolve_fiscal_year"](card.value)
                card.notes += f" | Fiscal year resolved: {fiscal_result}"
            
            elif "safe_cagr" in skill_name and card.computation_method == "CAGR":
                inputs = card.computation_inputs
                result, message = skill_namespace["safe_cagr"](
                    inputs.get("start"), inputs.get("end"), inputs.get("periods", 1)
                )
                if result is not None:
                    card.value = str(result)
                    card.verification_status = f"CAGR verified by {skill_name}"
                else:
                    card.validation_errors.append(f"CAGR error: {message}")
                    card.confidence = ConfidenceLevel.LOW
            
        except Exception as e:
            card.validation_errors.append(f"Skill {skill_name} execution error: {str(e)}")
        
        return card


class EnhancedEvidenceCardSystem:
    """Main system for enhanced evidence card processing"""
    
    def __init__(self, skills_path: Optional[Path] = None):
        self.validator = EvidenceCardValidator()
        self.aggregator = EvidenceCardAggregator(self.validator)
        self.enhancer = SkillTriggeredEnhancer(skills_path) if skills_path else None
    
    def process_cards(self, cards: List[Dict[str, Any]]) -> Tuple[Optional[str], List[str]]:
        """Process evidence cards and return final answer with errors"""
        
        # Convert dictionaries to EvidenceCard objects
        evidence_cards = []
        for card_data in cards:
            card = EvidenceCard.from_dict(card_data)
            
            # Apply skill enhancements
            if self.enhancer:
                card = self.enhancer.enhance_card(card)
            
            evidence_cards.append(card)
        
        # Aggregate cards
        final_card, errors = self.aggregator.aggregate_cards(evidence_cards)
        
        if final_card:
            return final_card.value, errors
        else:
            return None, errors or ["Failed to aggregate evidence cards"]
    
    def create_retrieve_card(self, 
                           value: str,
                           source_file: str,
                           unit_header: str,
                           table_key: str,
                           raw_snippet: str,
                           confidence: str = "medium") -> EvidenceCard:
        """Create a retrieve evidence card"""
        return EvidenceCard(
            value=value,
            card_type=CardType.RETRIEVE,
            source_file=source_file,
            unit_header=unit_header,
            table_key=table_key,
            raw_snippet=raw_snippet,
            confidence=ConfidenceLevel(confidence)
        )
    
    def create_think_card(self,
                         value: str,
                         method: str,
                         inputs: Dict[str, Any],
                         computation: str,
                         confidence: str = "medium") -> EvidenceCard:
        """Create a think evidence card"""
        return EvidenceCard(
            value=value,
            card_type=CardType.THINK,
            computation_method=method,
            computation_inputs=inputs,
            notes=computation,
            confidence=ConfidenceLevel(confidence)
        )