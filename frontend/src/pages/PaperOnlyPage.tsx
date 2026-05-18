import WelcomePage from "../components/WelcomePage";

export default function PaperOnlyPage() {
  return (
    <WelcomePage
      title="纯论文复现（无代码）"
      placeholder={"粘贴论文 URL 或描述实验内容...\n例如：https://arxiv.org/abs/2301.xxxxx 复现 Figure 3 的消融实验"}
      suggestions={[
        "复现注意力机制消融实验",
        "重现论文中的数据增强对比",
        "验证超参数敏感性分析",
      ]}
      requireGithubUrl={false}
      basePath="/paper-only"
    />
  );
}
