# Website booking webhook — integration guide

For the team that runs the Break Protection website.

After a customer **completes the ₹99 payment** on the "Book your appointment" form, send the booking to this address. Send one request per paid booking.

## Endpoint

```
POST https://<BP Analytics server>/api/v1/public/website-leads
```

Authentication: the API key we give you, in either of these places:

- the header `X-Api-Key: <key>` (preferred)
- the query string `?key=<key>`, if your platform can't set headers

The body can be JSON (`Content-Type: application/json`) or a normal form post (`application/x-www-form-urlencoded` or `multipart/form-data`).

## Fields

| Field | Required | Example | Notes |
|---|---|---|---|
| `full_name` | yes | `Anita Das` | `name` also accepted |
| `mobile` | yes | `+91 90087 77088` | at least 10 digits; `phone` or `whatsapp` also accepted |
| `email` | no | `anita@example.com` | |
| `country` | no | `India` | |
| `state` | no | `Kerala` | |
| `preferred_store` | recommended | `Kochi` | the store name as shown on the form |
| `store_id` | optional | `31` | our store id, if you load the store list from us (see below); most exact |
| `phone_brand` | no | `Apple` | |
| `phone_model` | no | `iPhone 15 Pro` | |
| `preferred_date` | no | `2026-10-05` | YYYY-MM-DD, or DD/MM/YYYY |
| `payment_id` | yes* | `pay_ABC123` | your payment gateway's payment / transaction id |
| `payment_status` | yes* | `captured` | `paid`, `success`, `captured` or `completed` count as paid |
| `amount` | no | `99` | |
| `entry_id` | recommended | `WEB-1001` | your unique id for this booking |

\* We only create a lead for a paid booking. Send `payment_status`, or at least `payment_id`.

If you send the same `entry_id` again, for example as an automatic retry, it does not create a second lead. Each new `entry_id` is a new lead, even when it's the same customer.

## Example

```bash
curl -X POST "https://<server>/api/v1/public/website-leads" \
  -H "X-Api-Key: <key>" -H "Content-Type: application/json" \
  -d '{"entry_id":"WEB-1001","full_name":"Anita Das","mobile":"+91 90087 77088",
       "email":"anita@example.com","country":"India","state":"Kerala","preferred_store":"Kochi",
       "phone_brand":"Apple","phone_model":"iPhone 15 Pro","preferred_date":"2026-10-05",
       "payment_id":"pay_ABC123","payment_status":"captured","amount":99}'
```

## Responses

| HTTP | `status` | Meaning |
|---|---|---|
| 200 | `created` | lead created (`lead_id` returned) |
| 200 | `duplicate` | this `entry_id` was already received; nothing new was created |
| 200 | `rejected_unpaid` | the payment is not confirmed, so no lead was created (the call is still logged) |
| 401 | — | missing or wrong API key |
| 422 | — | `full_name` or a valid mobile number is missing |
| 429 | — | too many requests (limit: 60 a minute) |

## Store list (optional, recommended)

To make "Preferred store" match exactly, your form can load our store list and send the chosen `store_id`:

```
GET https://<server>/api/v1/public/stores   (same API key)
→ {"stores": [{"id": 31, "name": "Kochi", "state": "Kerala", "country": "India"}, …]}
```
