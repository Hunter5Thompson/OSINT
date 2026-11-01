import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { SourceReference } from "./SourceReference";

it.each(["https://example.test/report", "http://example.test/report"])("opens a web reference: %s", reference => {
  render(<SourceReference reference={reference} />);
  expect(screen.getByRole("link")).toHaveAttribute("href", reference);
  expect(screen.getByRole("link")).toHaveAttribute("rel", "noopener noreferrer");
});
it.each(["urn:odin:123", "javascript:alert(1)", "data:text/html,hello", "https://user:secret@example.test", "/relative", "not a URL"])("keeps non-web or credential-bearing reference as text: %s", reference => {
  render(<SourceReference reference={reference} />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByText(reference)).toBeInTheDocument();
});
