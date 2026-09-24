/// <reference types="nativewind/types" />

// global.css is compiled by NativeWind through Metro; TypeScript 6 wants a
// declaration for side-effect imports of it.
declare module "*.css";
