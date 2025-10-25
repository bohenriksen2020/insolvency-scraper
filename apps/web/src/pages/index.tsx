import Head from "next/head";

export default function Home() {
  return (
    <>
      <Head>
        <title>Insolvency Intelligence</title>
        <meta name="description" content="Unified Danish insolvency data explorer" />
      </Head>
      <main style={{ fontFamily: "system-ui", padding: "2rem" }}>
        <h1>Insolvency Intelligence</h1>
        <p>
          This Next.js frontend will consume the aggregator API to present data from CVR and
          Statstidende in a unified view.
        </p>
        <p>
          Start all services with <code>docker compose up --build</code> and visit the web app on
          <a href="http://localhost:3000" style={{ marginLeft: "0.3rem" }}>localhost:3000</a>.
        </p>
      </main>
    </>
  );
}
