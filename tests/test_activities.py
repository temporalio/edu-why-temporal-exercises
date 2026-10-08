"""Each Activity calls its service, returns the record's id, and reports failures
in a way Temporal can show and act on.

The happy paths run each Activity against the real stub app, served in memory
through an httpx transport, so they check the real request and response. The
failure paths use a transport that fails on purpose.

How a failure is reported matters twice over. Temporal records a failure's whole
cause chain, and httpx's errors carry long ones, enough to pass the failure size
limit, so the Web UI would show "Failure exceeds size limit." instead of the
reason. So each Activity raises an ApplicationError whose message names the
service and the reason, with the chain dropped. And the failure says whether to
retry: an unreachable service, a timeout or a server error may clear up, so those
retry, while a 4xx means the Activity sent a bad request, which retrying can't fix.
"""

import httpx
import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from delivery.activities import DeliveryActivities
from delivery.models import Order
from delivery.stubs import dispatch, payment, restaurant


# --- helpers -----------------------------------------------------------------

def an_order() -> Order:
    return Order(order_id="order-1", amount_cents=1999, description="1 x margherita")


async def run(activities: DeliveryActivities, activity_name: str, order: Order):
    return await ActivityEnvironment().run(getattr(activities, activity_name), order)


async def ledger(stub_app, path: str) -> list[dict]:
    """The records a stub app holds, read through its own API."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=stub_app), base_url="http://stub") as client:
        response = await client.get(path)
        return response.json()


def failing_transport(failure) -> httpx.MockTransport:
    """A transport whose every request ends in `failure`: an exception to raise,
    or a status code to answer with."""
    def handle(request: httpx.Request) -> httpx.Response:
        if isinstance(failure, int):
            return httpx.Response(failure, request=request)
        raise failure(request)
    return httpx.MockTransport(handle)


async def failure_from(activity_name: str, failure) -> ApplicationError:
    activities = DeliveryActivities(transport=failing_transport(failure))
    with pytest.raises(ApplicationError) as raised:
        await run(activities, activity_name, an_order())
    return raised.value


def refused(request: httpx.Request) -> Exception:
    return httpx.ConnectError("All connection attempts failed", request=request)


def timed_out(request: httpx.Request) -> Exception:
    return httpx.ReadTimeout("timed out", request=request)


def assert_short(failure: ApplicationError) -> None:
    """No cause chain, so Temporal records only this one short failure."""
    assert failure.__cause__ is None
    assert failure.__suppress_context__


# --- happy paths ---------------------------------------------------------------

async def test_charge_payment_charges_the_order_once_and_returns_the_charge_id(tmp_path):
    stub = payment.create_app(ledger_path=tmp_path / "payment.json", delay_seconds=0)
    activities = DeliveryActivities(transport=httpx.ASGITransport(app=stub))

    charge_id = await run(activities, "charge_payment", an_order())

    charges = await ledger(stub, "/ledger")
    assert len(charges) == 1
    assert charges[0]["charge_id"] == charge_id
    assert charges[0]["order_id"] == "order-1"
    assert charges[0]["amount_cents"] == 1999


async def test_send_to_restaurant_creates_one_ticket_and_returns_its_id(tmp_path):
    stub = restaurant.create_app(ledger_path=tmp_path / "restaurant.json", delay_seconds=0)
    activities = DeliveryActivities(transport=httpx.ASGITransport(app=stub))

    ticket_id = await run(activities, "send_to_restaurant", an_order())

    tickets = await ledger(stub, "/tickets")
    assert len(tickets) == 1
    assert tickets[0]["ticket_id"] == ticket_id
    assert tickets[0]["order_id"] == "order-1"


async def test_dispatch_driver_creates_one_dispatch_and_returns_its_id(tmp_path):
    stub = dispatch.create_app(ledger_path=tmp_path / "dispatch.json", delay_seconds=0)
    activities = DeliveryActivities(transport=httpx.ASGITransport(app=stub))

    dispatch_id = await run(activities, "dispatch_driver", an_order())

    dispatches = await ledger(stub, "/dispatches")
    assert len(dispatches) == 1
    assert dispatches[0]["dispatch_id"] == dispatch_id
    assert dispatches[0]["order_id"] == "order-1"


# --- an unreachable service: retry ------------------------------------------------

async def test_charge_payment_reports_an_unreachable_payment_service():
    failure = await failure_from("charge_payment", refused)
    assert failure.message == "payment service unreachable: All connection attempts failed"
    assert not failure.non_retryable
    assert_short(failure)


async def test_send_to_restaurant_reports_an_unreachable_restaurant_service():
    failure = await failure_from("send_to_restaurant", refused)
    assert failure.message == "restaurant service unreachable: All connection attempts failed"
    assert not failure.non_retryable
    assert_short(failure)


async def test_dispatch_driver_reports_an_unreachable_dispatch_service():
    failure = await failure_from("dispatch_driver", refused)
    assert failure.message == "dispatch service unreachable: All connection attempts failed"
    assert not failure.non_retryable
    assert_short(failure)


# --- a service that doesn't answer in time: retry ----------------------------------

async def test_charge_payment_reports_a_payment_service_timeout():
    failure = await failure_from("charge_payment", timed_out)
    assert failure.message == "payment service timed out"
    assert not failure.non_retryable
    assert_short(failure)


async def test_send_to_restaurant_reports_a_restaurant_service_timeout():
    failure = await failure_from("send_to_restaurant", timed_out)
    assert failure.message == "restaurant service timed out"
    assert not failure.non_retryable
    assert_short(failure)


async def test_dispatch_driver_reports_a_dispatch_service_timeout():
    failure = await failure_from("dispatch_driver", timed_out)
    assert failure.message == "dispatch service timed out"
    assert not failure.non_retryable
    assert_short(failure)


# --- a server error: retry -----------------------------------------------------

async def test_charge_payment_reports_a_payment_server_error():
    failure = await failure_from("charge_payment", 503)
    assert failure.message == "payment service returned 503"
    assert not failure.non_retryable
    assert_short(failure)


async def test_send_to_restaurant_reports_a_restaurant_server_error():
    failure = await failure_from("send_to_restaurant", 503)
    assert failure.message == "restaurant service returned 503"
    assert not failure.non_retryable
    assert_short(failure)


async def test_dispatch_driver_reports_a_dispatch_server_error():
    failure = await failure_from("dispatch_driver", 503)
    assert failure.message == "dispatch service returned 503"
    assert not failure.non_retryable
    assert_short(failure)


# --- a rejected request: don't retry ---------------------------------------------

async def test_charge_payment_does_not_retry_a_rejected_request():
    failure = await failure_from("charge_payment", 422)
    assert failure.message == "payment service rejected the request: 422"
    assert failure.non_retryable
    assert_short(failure)


async def test_send_to_restaurant_does_not_retry_a_rejected_request():
    failure = await failure_from("send_to_restaurant", 422)
    assert failure.message == "restaurant service rejected the request: 422"
    assert failure.non_retryable
    assert_short(failure)


async def test_dispatch_driver_does_not_retry_a_rejected_request():
    failure = await failure_from("dispatch_driver", 422)
    assert failure.message == "dispatch service rejected the request: 422"
    assert failure.non_retryable
    assert_short(failure)
