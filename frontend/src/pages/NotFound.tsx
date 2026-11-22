import { Link } from "react-router";

export default function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center px-4 text-center">
      <div>
        <p className="text-sm font-medium text-brand-700">404</p>
        <h1 className="mt-2 text-2xl font-semibold">Page not found</h1>
        <Link to="/" className="mt-6 inline-block text-sm font-medium text-brand-700 underline">
          Back to the overview
        </Link>
      </div>
    </main>
  );
}
