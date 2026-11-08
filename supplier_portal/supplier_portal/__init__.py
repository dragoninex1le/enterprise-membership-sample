"""The EMS supplier portal — where a buyer's suppliers send their invoices.

**The feature.** A supplier is not an EMS user. They belong to the supplier network
(*SupplierLink*, a fictional network standing in for any supplier or procurement
network), sign in there, and send invoices to the businesses they supply. When a
buyer — an EMS tenant — links its SupplierLink buyer account to EMS, that buyer's
suppliers can submit invoices straight into the tenant's accounts payable and follow
them through approval, without an EMS login.

**Why it needs a connector.** Only SupplierLink knows who the supplier's contact is.
EMS verifies SupplierLink's signed assertion about them, and Porth issues a session
for a person it never authenticated: a *delegated principal* (Porth's
``docs/delegated-mint.md``). The session carries the tenant (from the buyer's link),
the contact (``external_id``), the supplier (``store_external_id`` — which the app
uses to show each supplier only their own invoices) and the role SupplierLink gives
the contact, mapped to an EMS role by the tenant.

The flow:

1. SupplierLink signs an assertion (ES256) for its contact: who, which supplier,
   which buyer, which role, valid for minutes.
2. The supplier's client posts it to ``https://{tenant}.api.{slot}.{zone}/suppliers/session``.
   ``assertion`` verifies it with SupplierLink's public key; EMS holds no signing key.
3. ``links`` finds the buyer's link, which holds the tenant's ``PersistedContext``,
   captured when the tenant admin linked the account.
4. ``porth_session`` asks Porth's ``porth-delegated-mint`` service for a session in that
   tenant, over Porth's internal plane.
5. The client uses the ``prth_`` bearer on ``/suppliers/*`` (the sample app).

This is its own function with its own porth-common: the mint rides the internal plane
as porth-common 0.0.18+ defines it, while the sample app is held below 0.0.18.
"""

CONNECTOR = "supplierlink"
