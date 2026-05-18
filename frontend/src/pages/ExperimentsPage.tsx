import WelcomePage from "../components/WelcomePage";

export default function ExperimentsPage() {
  return (
    <WelcomePage
      title="自动化实验矩阵"
      placeholder={"描述你的实验设计...\n例如：对 ResNet-50 做 learning rate {1e-3, 1e-4, 1e-5} × batch size {32, 64, 128} 的网格搜索"}
      suggestions={[
        "超参数网格搜索",
        "多种 backbone 对比实验",
        "不同数据集上的泛化测试",
      ]}
      requireGithubUrl={false}
      basePath="/experiments"
    />
  );
}
