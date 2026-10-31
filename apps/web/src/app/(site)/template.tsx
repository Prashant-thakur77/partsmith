/** Every navigation inside the site fades the new page in (200 ms, CSS only; instant with reduced motion). */
export default function SiteTemplate({ children }: { children: React.ReactNode }) {
  return <div className="page-in">{children}</div>;
}
