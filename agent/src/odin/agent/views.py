"""Компактные представления доменных объектов для модели: только нужное для ответа."""

from datetime import datetime
from typing import Any

from odin.domain.formatting import duration
from odin.domain.hotel import MEAL_LABELS, HotelOffer
from odin.domain.order import Cart, Order
from odin.domain.plan import SLOT_LABELS, Explanation, Issue, Offer, PlanDiff, TripPlan
from odin.domain.ranking import Ranked
from odin.domain.request import TripRequest
from odin.domain.scoring.destinations import DestinationFacts
from odin.domain.tags import TAG_LABELS
from odin.domain.transfer import TransferOffer
from odin.domain.transport import TransportKind, TransportOffer


def request_view(request: TripRequest) -> dict[str, Any]:
    """Только заполненные поля запроса, плюс подпись состава группы."""
    data = request.model_dump(mode="json")
    if set(request.transport_kinds) == set(TransportKind):
        del data["transport_kinds"]
    if not request.free_cancellation:
        del data["free_cancellation"]
    view = _compact(data)
    view["party_label"] = request.party.label()
    return view


def destination_view(item: Ranked[DestinationFacts]) -> dict[str, Any]:
    facts = item.option
    destination = facts.destination
    return {
        "id": destination.id,
        "name": destination.name,
        "country": destination.country,
        "description": destination.description,
        "price_from_rub": facts.price_from_rub,
        "price_note": "ориентир: самый дешёвый путь туда-обратно + самый дешёвый подходящий отель",
        "travel_time": duration(facts.travel_minutes),
        "weather": facts.weather.label(),
        "entry": destination.entry_note,
        "tags": [TAG_LABELS[tag] for tag in destination.tags],
        **_explained(item),
    }


def hotel_view(offer: HotelOffer) -> dict[str, Any]:
    hotel = offer.hotel
    free_until = offer.cancellation.free_until
    return _compact(
        {
            "id": offer.id,
            "name": hotel.name,
            "stars": hotel.stars,
            "rating": hotel.rating,
            "area": hotel.area,
            "room": offer.room,
            "meal": MEAL_LABELS[offer.meal_plan],
            "total_price_rub": offer.total_price_rub,
            "rooms": offer.rooms,
            "nights": offer.nights,
            "free_cancellation_until": free_until.isoformat() if free_until else None,
            "refundable": offer.cancellation.refundable,
            "distance_to_beach_m": hotel.distance_to_beach_m,
            "distance_to_center_km": hotel.distance_to_center_km,
            "distance_to_airport_km": hotel.distance_to_airport_km,
            "check_in_from": hotel.check_in_from.strftime("%H:%M"),
            "check_out_until": hotel.check_out_until.strftime("%H:%M"),
            "pets_allowed": hotel.pets_allowed,
            "amenities": [TAG_LABELS[tag] for tag in hotel.tags],
        }
    )


def transport_view(offer: TransportOffer) -> dict[str, Any]:
    return {
        "id": offer.id,
        "kind": offer.kind.value,
        "title": offer.title,
        "departs": _local(offer.departs_at),
        "arrives": _local(offer.arrives_at),
        "travel_time": duration(offer.duration_minutes),
        "stops": offer.stops,
        "layovers": [duration(minutes) for minutes in offer.layovers_minutes],
        "total_price_rub": offer.total_price_rub,
        "baggage_included": offer.baggage_included,
        "refundable": offer.refundable,
        "pets_allowed": offer.pets_allowed,
    }


def transfer_view(offer: TransferOffer) -> dict[str, Any]:
    return {
        "id": offer.id,
        "title": offer.title,
        "pickup": _local(offer.pickup_at),
        "arrives": _local(offer.arrive_at),
        "travel_time": duration(offer.duration_minutes),
        "total_price_rub": offer.total_price_rub,
        "child_seat": offer.child_seat,
        "pets_allowed": offer.pets_allowed,
        "meet_and_greet": offer.meet_and_greet,
    }


def offer_view(offer: Offer) -> dict[str, Any]:
    if isinstance(offer, HotelOffer):
        return hotel_view(offer)
    if isinstance(offer, TransportOffer):
        return transport_view(offer)
    return transfer_view(offer)


def ranked_view(item: Ranked[Any]) -> dict[str, Any]:
    """Предложение вместе с объяснением: плюсы, чем пожертвовано, риски."""
    return {**offer_view(item.option), **_explained(item)}


def plan_view(plan: TripPlan) -> dict[str, Any]:
    parts = {}
    for slot, label in SLOT_LABELS.items():
        offer = plan.get(slot)
        if offer is not None:
            explanation = plan.explanations.get(slot)
            parts[slot.value] = {
                "label": label,
                **offer_view(offer),
                **(_explanation_view(explanation) if explanation else {}),
            }
    return _compact(
        {
            "revision": plan.revision,
            "destination": {
                "id": plan.destination.id,
                "name": plan.destination.name,
                "country": plan.destination.country,
            },
            "check_in": plan.check_in.isoformat(),
            "check_out": plan.check_out.isoformat(),
            "nights": plan.nights,
            "party": plan.party.label(),
            "weather": plan.weather.label() if plan.weather else None,
            **parts,
            "total_price_rub": plan.total_price_rub,
            "chosen_by_user": [slot.value for slot in plan.pinned],
            "issues": [issue_view(issue) for issue in plan.issues],
        }
    )


def issue_view(issue: Issue) -> dict[str, Any]:
    return {
        "severity": issue.severity.value,
        "code": issue.code.value,
        "message": issue.message,
        "parts": [slot.value for slot in issue.slots],
    }


def diff_view(diff: PlanDiff) -> dict[str, Any]:
    return {
        "parts": [
            _compact(
                {
                    "part": change.slot.value,
                    "status": change.kind.value,
                    "was": change.before,
                    "now": change.after,
                    "price_change_rub": change.price_delta_rub,
                }
            )
            for change in diff.changes
        ],
        "total_price_change_rub": diff.price_delta_rub,
    }


def cart_view(cart: Cart) -> dict[str, Any]:
    return {
        "id": cart.id,
        "status": cart.status.value,
        "items": [
            {
                "part": item.slot.value,
                "title": item.title,
                "price_rub": item.price_rub,
                "conditions": item.conditions,
            }
            for item in cart.items
        ],
        "total_price_rub": cart.total_price_rub,
    }


def order_view(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "total_price_rub": order.total_price_rub,
        "payment": {
            "transaction_id": order.receipt.transaction_id,
            "method": order.receipt.method,
            "note": "имитация: деньги не списывались",
        },
        "bookings": [
            {
                "part": booking.slot.value,
                "title": booking.title,
                "confirmation_code": booking.confirmation_code,
            }
            for booking in order.bookings
        ],
    }


def _explained(item: Ranked[Any]) -> dict[str, Any]:
    return _explanation_view(item.explanation())


def _explanation_view(explanation: Explanation) -> dict[str, Any]:
    return _compact(
        {
            "score": explanation.score,
            "pros": explanation.pros,
            "cons": explanation.cons,
            "risks": explanation.risks,
        }
    )


def _local(moment: datetime) -> str:
    """Местное время пункта, как на табло: '2026-11-10 11:15'."""
    return moment.strftime("%Y-%m-%d %H:%M")


def _compact(value: Any) -> Any:
    """Убирает пустые значения (None, '', [], {}) рекурсивно; False и 0 остаются."""
    if isinstance(value, dict):
        cleaned = {key: _compact(item) for key, item in value.items()}
        return {key: item for key, item in cleaned.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_compact(item) for item in value]
    return value
