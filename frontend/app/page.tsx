'use client'

import dynamic from 'next/dynamic';

// Dynamically import the App component with SSR disabled
const App = dynamic(() => import('./components/App'), {
  ssr: false,
});

export default function Page() {
  return <App />;
}
