from typing import List, Optional
from pydantic import BaseModel, Field


class GlossaryTermRef(BaseModel):
    urn: str
    name: str
    description: Optional[str] = None


class OwnerRef(BaseModel):
    urn: str
    name: str
    type: Optional[str] = None


class DownstreamConsumer(BaseModel):
    urn: str
    name: str
    platform: str
    owners: List[OwnerRef] = Field(default_factory=list)


class AssertionRef(BaseModel):
    urn: str
    type: str
    status: str  # "PASSED", "FAILED" и т. п.


class EvidenceBundle(BaseModel):
    asset_urn: str
    field_name: str
    asset_name: Optional[str] = None
    field_glossary_terms: List[GlossaryTermRef] = Field(default_factory=list)
    dataset_glossary_terms: List[GlossaryTermRef] = Field(default_factory=list)
    asset_owners: List[OwnerRef] = Field(default_factory=list)
    downstream_consumers: List[DownstreamConsumer] = Field(default_factory=list)
    has_bi_consumer: bool = False
    failing_assertions: List[AssertionRef] = Field(default_factory=list)
    unresolvable_lineage_urns: List[str] = Field(default_factory=list)

    @property
    def all_glossary_terms(self) -> List[GlossaryTermRef]:
        """Объединённый список терминов глоссария уровня поля и набора данных."""
        seen = set()
        terms = []
        for term in self.field_glossary_terms + self.dataset_glossary_terms:
            if term.urn not in seen:
                seen.add(term.urn)
                terms.append(term)
        return terms
