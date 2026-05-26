import WelcomePage from "../components/WelcomePage";

export default function AutoResearchPage() {
  return (
    <WelcomePage
      title="自动化实验矩阵"
      placeholder={"粘贴 GitHub URL，描述自动化训练目标...\n例如：https://github.com/jingyaogong/minimind 帮我跑下自动化训练实验"}
      suggestions={[
        "帮我跑下 minimind 的自动化训练实验",
        "自动搜索学习率和 batch size",
        "按实验循环生成 autoresearch_report.md",
      ]}
      requireGithubUrl
      basePath="/auto-research"
      taskType="experiments"
      demoSubmitPath="/auto-research/demo/mock-run"
    />
  );
}
