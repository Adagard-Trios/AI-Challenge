'use client'
import { useLocation } from "react-router-dom";
import { useEffect } from "react";
import Link from "next/link";

const NotFound = () => {
  const location = useLocation();

  useEffect(() => {
    console.error("404 Error: User attempted to access non-existent route:", location.pathname);
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted">
      <div className="text-center">
        <h1 className="mb-4 text-4xl font-bold">404</h1>
        <p className="mb-4 text-xl text-muted-foreground">Oops! Page not found</p>
        {/* next/link rather than a bare <a>: "/" is a real Next route, so this
            is a client transition instead of a full document reload. */}
        <Link href="/" className="text-primary underline hover:text-primary/90 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
          Return to Home
        </Link>
      </div>
    </div>
  );
};

export default NotFound;
