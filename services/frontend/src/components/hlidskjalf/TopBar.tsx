import { NavLink } from "react-router-dom";

/**
 * Minimal TopBar stub for S1 Task 1.
 *
 * Full Hlíðskjalf Noir styling and nav behaviour land in Task 7.
 * For now: brand text + four NavLinks sufficient for routing tests.
 */
export function TopBar() {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        gap: "1.5rem",
        padding: "0.75rem 1.25rem",
        borderBottom: "1px solid rgba(255,255,255,0.08)",
        fontFamily: "serif",
      }}
    >
      <span style={{ fontStyle: "italic", letterSpacing: "0.05em" }}>Hlíðskjalf</span>
      <nav style={{ display: "flex", gap: "1rem", fontSize: "0.85rem", letterSpacing: "0.08em" }}>
        <NavLink to="/">HOME</NavLink>
        <NavLink to="/worldview">WORLDVIEW</NavLink>
        <NavLink to="/briefing">BRIEFING</NavLink>
        <NavLink to="/warroom">WAR ROOM</NavLink>
      </nav>
    </header>
  );
}
