import WelcomePage from "../components/WelcomePage";

export default function PolishPage() {
  return (
    <WelcomePage
      title="智能论文润色"
      placeholder={"粘贴需要润色的段落，或描述润色需求...\n例如：帮我把这段 Introduction 改得更学术化，目标期刊是 NeurIPS"}
      suggestions={[
        "润色 Abstract 段落",
        "改写 Related Work",
        "优化实验描述的表达",
      ]}
      requireGithubUrl={false}
      basePath="/polish"
    />
  );
}
