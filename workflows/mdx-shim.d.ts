declare module "*.mdx" {
  const Component: (props: Record<string, unknown>) => any;
  export default Component;
}
