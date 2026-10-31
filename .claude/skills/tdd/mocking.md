# When to Mock

Mock at **system boundaries** only:

- External APIs (payment, email, etc.)
- Databases (sometimes - prefer test DB)
- Time/randomness
- File system (sometimes)

Don't mock:

- Your own classes/modules
- Internal collaborators
- Anything you control

## Designing for Mockability

At system boundaries, design interfaces that are easy to mock:

**1. Use dependency injection**

Pass external dependencies in rather than creating them internally:

```typescript
// Easy to mock
function processPayment(order, paymentClient) {
  return paymentClient.charge(order.total);
}

// Hard to mock
function processPayment(order) {
  const client = new StripeClient(process.env.STRIPE_KEY);
  return client.charge(order.total);
}
```

**2. Prefer SDK-style interfaces over generic fetchers**

Create specific functions for each external operation instead of one generic function with conditional logic:

```typescript
// GOOD: Each function is independently mockable
const api = {
  getUser: (id) => fetch(`/users/${id}`),
  getOrders: (userId) => fetch(`/users/${userId}/orders`),
  createOrder: (data) => fetch('/orders', { method: 'POST', body: data }),
};

// BAD: Mocking requires conditional logic inside the mock
const api = {
  fetch: (endpoint, options) => fetch(endpoint, options),
};
```

The SDK approach means:
- Each mock returns one specific shape
- No conditional logic in test setup
- Easier to see which endpoints a test exercises
- Type safety per endpoint

## Boundaries to mock

- **Third-party APIs**: a stub returning canned responses. A unit test never makes a network call.
- **Control planes and deploy tooling**: never run a real ops call from a test.
- **Queues and schedulers**: a local fake; mock at the integration level.
- **A heavy subprocess**: run the real thing in the integration test where its output shape is what is being validated; mock it for unit tests of paths that do not depend on the output.
- **Time**: pin the clock for anything with an expiry or a timer.

## Boundaries NOT to mock

- **The storage layer**: use a real fake or a test schema. The storage interface IS the test surface.
- **Pure compute**: call it and assert. A mock here tests the mock.
- **Modules you own**: mocking one means the seam is in the wrong place; move the seam instead.
