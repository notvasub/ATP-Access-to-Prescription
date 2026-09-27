"""Two distinct call destinations, persisted locally and copied onto each new call."""

from pydantic import BaseModel, Field, model_validator


class Contacts(BaseModel):
    insurer_phone_number: str = Field(default="", pattern=r"^$|^\+[1-9]\d{7,14}$")
    doctor_phone_number: str = Field(default="", pattern=r"^$|^\+[1-9]\d{7,14}$")

    @model_validator(mode="after")
    def distinct_numbers(self):
        if self.insurer_phone_number and self.insurer_phone_number == self.doctor_phone_number:
            raise ValueError("The insurer and doctor must have different phone numbers.")
        return self


def load_contacts(store, settings):
    saved = store.get("contacts")
    if saved is None:
        saved = Contacts(
            insurer_phone_number=settings.insurer_phone_number or settings.demo_payer_phone_number,
            doctor_phone_number=settings.doctor_phone_number,
        ).model_dump()
        store.put("contacts", saved)
    return saved
