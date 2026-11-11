// Turns src/wire/schema.json (exported from server/src/karaoke/contract.py) into src/wire/generated.ts.
// Both outputs are gitignored. They are rebuilt before dev, build, and typecheck, so a Python change to the
// contract shows up as a TypeScript compile error on the page that needs updating, never as a runtime surprise.
//
// TODO pseudocode:
//   schema = JSON.parse(read("src/wire/schema.json"))
//   ts = await compile(schema, "Contract", { bannerComment: GENERATED_BANNER, unreachableDefinitions: true,
//                                             strictIndexSignatures: true, additionalProperties: false })
//   write("src/wire/generated.ts", ts)
throw new Error("not implemented");
