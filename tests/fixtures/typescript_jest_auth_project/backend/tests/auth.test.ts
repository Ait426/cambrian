import { authenticate } from "../src/middleware/authMiddleware";

test("auth middleware accepts an authorization header", () => {
  expect(authenticate("Bearer token")).toBe(true);
});
