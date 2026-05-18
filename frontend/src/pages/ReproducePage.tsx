import WelcomePage from "../components/WelcomePage";

export default function ReproducePage() {
  return (
    <WelcomePage
      title="复现任意顶会论文与代码"
      placeholder={"粘贴 GitHub URL，描述你想复现的内容...\n例如：https://github.com/karpathy/nanoGPT 帮我复现 Table 1 的结果"}
      suggestions={[
        "复现 nanoGPT 训练流程",
        "跑通 Stable Diffusion 推理",
        "复现 LoRA 微调实验",
      ]}
    />
  );
}
